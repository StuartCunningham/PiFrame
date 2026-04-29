"""Core slideshow engine — runs on the main thread."""
import json
import logging
import os
import random
import signal
import time
import subprocess
from datetime import datetime, time as dtime
from pathlib import Path

from PIL import Image, ImageOps

_log = logging.getLogger(__name__)

SUPPORTED_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
VIDEO_EXT = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'}


def _meta_path(image_path: str) -> Path:
    p = Path(image_path)
    return p.parent / (p.name + '.json')


def _load_meta(image_path: str) -> dict:
    new_path = _meta_path(image_path)
    if new_path.exists():
        try:
            return json.loads(new_path.read_text())
        except Exception:
            pass
    # Migrate from old stem-based path (photo.json → photo.jpg.json)
    old_path = Path(image_path).parent / (Path(image_path).stem + '.json')
    if old_path.exists():
        try:
            data = json.loads(old_path.read_text())
            new_path.write_text(json.dumps(data, indent=2))
            old_path.unlink()
            return data
        except Exception:
            pass
    return {}


def _load_image(path: str, size: tuple, fit_mode: str, bg_color: tuple,
                custom_scale: float = 1.0, custom_pan_x: float = 0.0,
                custom_pan_y: float = 0.0) -> Image.Image:
    img = Image.open(path).convert('RGB')
    img = ImageOps.exif_transpose(img)

    tw, th = size
    iw, ih = img.size

    if fit_mode == 'fill':
        scale = max(tw / iw, th / ih)
        img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
        left = (img.width - tw) // 2
        top = (img.height - th) // 2
        img = img.crop((left, top, left + tw, top + th))

    elif fit_mode == 'fit':
        scale = min(tw / iw, th / ih)
        img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
        canvas = Image.new('RGB', (tw, th), bg_color)
        canvas.paste(img, ((tw - img.width) // 2, (th - img.height) // 2))
        img = canvas

    elif fit_mode == 'stretch':
        img = img.resize((tw, th), Image.LANCZOS)

    elif fit_mode == 'custom':
        # Fit baseline then apply per-image scale + pan offsets.
        # custom_scale=1 reproduces letterbox; >1 zooms in, <1 zooms out.
        # custom_pan_x/y: ±1 shifts image by ±half display width/height.
        base = min(tw / iw, th / ih)
        s = max(0.01, base * custom_scale)
        rw, rh = max(1, int(iw * s)), max(1, int(ih * s))
        img = img.resize((rw, rh), Image.LANCZOS)
        cx = (tw - rw) // 2 + int(custom_pan_x * tw * 0.5)
        cy = (th - rh) // 2 + int(custom_pan_y * th * 0.5)
        canvas = Image.new('RGB', (tw, th), bg_color)
        canvas.paste(img, (cx, cy))
        img = canvas

    else:  # center (unknown fit_mode values fall here)
        if fit_mode not in ('center', ''):
            _log.warning('Unknown fit_mode %r, falling back to center', fit_mode)
        canvas = Image.new('RGB', (tw, th), bg_color)
        paste_x = max(0, (tw - iw) // 2)
        paste_y = max(0, (th - ih) // 2)
        crop_x = max(0, (iw - tw) // 2)
        crop_y = max(0, (ih - th) // 2)
        sub = img.crop((crop_x, crop_y,
                        crop_x + min(iw, tw), crop_y + min(ih, th)))
        canvas.paste(sub, (paste_x, paste_y))
        img = canvas

    return img


def _collect_photos(photo_dir: str, extensions: set, recursive: bool) -> list:
    root = Path(photo_dir)
    if not root.exists():
        return []
    pattern = '**/*' if recursive else '*'
    return [
        str(p) for p in root.glob(pattern)
        if p.suffix.lower() in extensions
    ]


def _in_schedule(on_str: str, off_str: str) -> bool:
    now = datetime.now().time().replace(second=0, microsecond=0)
    on = dtime.fromisoformat(on_str)
    off = dtime.fromisoformat(off_str)
    if on <= off:
        return on <= now <= off
    return now >= on or now <= off   # overnight schedule


def _hdmi_power(on: bool):
    """Toggle HDMI output on Pi using vcgencmd."""
    try:
        cmd = 'display_power 1' if on else 'display_power 0'
        subprocess.run(['vcgencmd', cmd], capture_output=True)
    except FileNotFoundError:
        pass


_STATE_FILE = '.piframe_state.json'
_STATE_SAVE_INTERVAL = 10   # seconds between saves


class Slideshow:
    def __init__(self, config, state, display, overlay_engine):
        self._config = config
        self._state = state
        self._display = display
        self._overlay = overlay_engine
        self._last_photo_reload = 0
        self._last_state_save = 0
        self._schedule_blanked = False
        self._stop = False

    def run(self):
        """Main loop — call from the main thread."""
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, '_stop', True))
        self._display.start()
        self._reload_photos()

        while not self._stop:
            if not self._display.pump_events():
                break

            # ── Schedule ──────────────────────────────────────────────────────
            sched = self._config.schedule
            if sched['enabled']:
                active = _in_schedule(sched['on_time'], sched['off_time'])
                if not active:
                    if not self._schedule_blanked:
                        self._schedule_blanked = True
                        if sched['off_action'] == 'off':
                            _hdmi_power(False)
                        else:
                            self._display.blank()
                    self._sleep_checking(30)
                    continue
                elif self._schedule_blanked:
                    self._schedule_blanked = False
                    if sched['off_action'] == 'off':
                        _hdmi_power(True)

            # ── Commands from web UI ──────────────────────────────────────────
            cmd = self._state.pop_command()
            if cmd == 'next':
                _log.info("Command: next")
                self._advance(+1)
            elif cmd == 'prev':
                _log.info("Command: prev")
                self._advance(-1)
            elif cmd == 'reload':
                _log.info("Command: reload")
                self._reload_photos()

            # ── Periodic photo-dir reload (every 30 min) ──────────────────────
            if time.time() - self._last_photo_reload > 1800:
                self._reload_photos()

            # ── Display ───────────────────────────────────────────────────────
            if not self._state.paused:
                interval = self._show_current()
                self._sleep_checking(interval)
                self._advance(+1)
            else:
                self._sleep_checking(1)

        self._display.stop()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_current(self) -> float:
        """Display the current photo/video and return the interval to sleep before advancing."""
        photos = self._state.photo_list
        if not photos:
            self._display.blank()
            return float(self._config.slideshow['interval'])

        idx = self._state.photo_index % len(photos)
        path = photos[idx]
        meta = _load_meta(path)

        if meta.get('skip'):
            return 0.0

        self._state.current_photo = path
        _log.info("Displaying: %s", os.path.basename(path))

        if Path(path).suffix.lower() in VIDEO_EXT:
            return self._show_video(path, meta)

        cfg_sl = self._config.slideshow
        mode = self._config.display.get('mode', 'hdmi')
        bg = tuple(self._config.display.get(mode, {}).get('background_color', [0, 0, 0]))
        fit_mode = meta.get('fit_mode') or cfg_sl['fit_mode']

        try:
            img = _load_image(
                path, self._display.size, fit_mode, bg,
                custom_scale=float(meta.get('custom_scale', 1.0)),
                custom_pan_x=float(meta.get('custom_pan_x', 0.0)),
                custom_pan_y=float(meta.get('custom_pan_y', 0.0)),
            )
            img = self._overlay.apply(img, path, meta)
            transition = cfg_sl.get('transition', 'cut')
            self._display.show(img, transition)
        except Exception:
            _log.warning('Failed to display %s', path)
            return 0.0

        return float(meta.get('duration') or cfg_sl['interval'])

    def _show_video(self, path: str, meta: dict) -> float:
        """Play a video file; returns 0 so the slideshow advances immediately after."""
        video_cfg = self._config.slideshow.get('video', {})
        volume = int(video_cfg.get('volume', 50))
        mode = self._config.display.get('mode', 'hdmi')
        if mode != 'hdmi' or not hasattr(self._display, 'play_video'):
            _log.info('Video skipped (not an HDMI display): %s', path)
            return 0.0

        # Peek-and-requeue so the command still takes effect after mpv exits.
        pending = []

        def command_cb():
            cmd = self._state.pop_command()
            if cmd in ('next', 'prev'):
                pending.append(cmd)
                return cmd
            return cmd  # 'reload' and None are harmless to return

        try:
            self._display.play_video(
                path, volume, meta=meta,
                stop_flag=lambda: self._stop,
                command_cb=command_cb,
            )
        except Exception:
            _log.warning('Failed to play video %s', path)

        # Replay any next/prev command so _advance is called by the main loop.
        for cmd in pending:
            self._state.send_command(cmd)

        return 0.0

    def _advance(self, delta: int):
        photos = self._state.photo_list
        if not photos:
            return
        idx = (self._state.photo_index + delta) % len(photos)
        self._state.photo_index = idx
        self._maybe_save_state()

    def _maybe_save_state(self):
        now = time.time()
        if now - self._last_state_save >= _STATE_SAVE_INTERVAL:
            self._last_state_save = now
            self._state.save(_STATE_FILE)

    def _reload_photos(self):
        cfg = self._config.slideshow
        exts = {f'.{e.lower()}' for e in cfg.get('supported_formats', [])}
        video_cfg = cfg.get('video', {})
        if video_cfg.get('enabled'):
            exts |= {f'.{e.lower()}' for e in video_cfg.get('formats', [])}
        photos = _collect_photos(cfg['photo_dir'], exts, cfg.get('recursive', True))

        if not photos:
            _log.warning('No photos found in %s', cfg['photo_dir'])

        if cfg.get('shuffle'):
            random.shuffle(photos)

        self._state.photo_list = photos
        self._last_photo_reload = time.time()

        if photos:
            # Resume at the previously displayed file if still present.
            current = self._state.current_photo
            if current and current in photos:
                self._state.photo_index = photos.index(current)
            else:
                self._state.photo_index = self._state.photo_index % len(photos)

    def _sleep_checking(self, seconds: float):
        """Sleep in small increments so pump_events and commands stay responsive."""
        deadline = time.time() + seconds
        while time.time() < deadline and not self._stop:
            if not self._display.pump_events():
                return
            cmd = self._state.pop_command()
            if cmd == 'next':
                self._advance(+1)
                return
            elif cmd == 'prev':
                self._advance(-1)
                return
            elif cmd == 'reload':
                self._reload_photos()
            time.sleep(0.25)
