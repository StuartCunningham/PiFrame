"""Core slideshow engine — runs on the main thread."""
import os
import random
import time
import subprocess
from datetime import datetime, time as dtime
from pathlib import Path

from PIL import Image

SUPPORTED_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}


def _exif_rotate(img: Image.Image) -> Image.Image:
    try:
        from PIL.ExifTags import TAGS
        exif = img._getexif()  # type: ignore[attr-defined]
        if exif:
            for tag, val in exif.items():
                if TAGS.get(tag) == 'Orientation':
                    rotations = {3: 180, 6: 270, 8: 90}
                    if val in rotations:
                        return img.rotate(rotations[val], expand=True)
    except Exception:
        pass
    return img


def _load_image(path: str, size: tuple, fit_mode: str,
                bg_color: tuple) -> Image.Image:
    img = Image.open(path).convert('RGB')
    img = _exif_rotate(img)

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

    else:  # center
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


class Slideshow:
    def __init__(self, config, state, display, overlay_engine):
        self._config = config
        self._state = state
        self._display = display
        self._overlay = overlay_engine
        self._last_photo_reload = 0
        self._schedule_blanked = False

    def run(self):
        """Main loop — call from the main thread."""
        self._display.start()
        self._reload_photos()

        while True:
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
                self._advance(+1)
            elif cmd == 'prev':
                self._advance(-1)
            elif cmd == 'reload':
                self._reload_photos()

            # ── Periodic photo-dir reload (every 5 min) ───────────────────────
            if time.time() - self._last_photo_reload > 300:
                self._reload_photos()

            # ── Display ───────────────────────────────────────────────────────
            if not self._state.paused:
                self._show_current()
                self._sleep_checking(self._config.slideshow['interval'])
                self._advance(+1)
            else:
                self._sleep_checking(1)

        self._display.stop()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_current(self):
        photos = self._state.photo_list
        if not photos:
            self._display.blank()
            return

        idx = self._state.photo_index % len(photos)
        path = photos[idx]
        self._state.current_photo = path

        cfg_sl = self._config.slideshow
        bg = tuple(self._config.display['hdmi'].get('background_color', [0, 0, 0]))

        try:
            img = _load_image(path, self._display.size, cfg_sl['fit_mode'], bg)
            img = self._overlay.apply(img, path)
            transition = cfg_sl.get('transition', 'cut')
            self._display.show(img, transition)
        except Exception:
            # Skip broken images
            self._advance(+1)

    def _advance(self, delta: int):
        photos = self._state.photo_list
        if not photos:
            return
        idx = (self._state.photo_index + delta) % len(photos)
        self._state.photo_index = idx

    def _reload_photos(self):
        cfg = self._config.slideshow
        exts = {f'.{e.lower()}' for e in cfg.get('supported_formats', [])}
        photos = _collect_photos(cfg['photo_dir'], exts, cfg.get('recursive', True))

        if cfg.get('shuffle'):
            random.shuffle(photos)

        self._state.photo_list = photos
        self._last_photo_reload = time.time()

        # Keep index in bounds after reload
        if photos:
            self._state.photo_index = self._state.photo_index % len(photos)

    def _sleep_checking(self, seconds: float):
        """Sleep in small increments so pump_events and commands stay responsive."""
        deadline = time.time() + seconds
        while time.time() < deadline:
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
