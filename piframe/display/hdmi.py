"""HDMI display driver using pygame."""
import logging
import os
import subprocess
import time
import pygame
from PIL import Image

_log = logging.getLogger(__name__)


class HDMIDisplay:
    def __init__(self, config):
        self._cfg = config.display['hdmi']
        self._width = self._cfg['width']
        self._height = self._cfg['height']
        self._fullscreen = self._cfg['fullscreen']
        self._rotation = self._cfg['rotation']
        self._screen = None
        self._current_surface = None

    def start(self):
        # When launched over SSH without a display env, auto-detect the
        # running Wayland or X11 session so pygame can reach the screen.
        if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
            import pathlib
            xdg = f'/run/user/{os.getuid()}'
            if pathlib.Path(f'{xdg}/wayland-0').exists():
                os.environ.setdefault('XDG_RUNTIME_DIR', xdg)
                os.environ['WAYLAND_DISPLAY'] = 'wayland-0'
                os.environ['SDL_VIDEODRIVER'] = 'wayland'
            elif pathlib.Path('/tmp/.X0-lock').exists():
                os.environ['DISPLAY'] = ':0'
                os.environ['SDL_VIDEODRIVER'] = 'x11'

        os.environ.setdefault('SDL_VIDEO_CENTERED', '1')
        pygame.init()
        pygame.display.set_caption('PiFrame')

        if self._cfg.get('hide_cursor', True):
            pygame.mouse.set_visible(False)

        flags = pygame.FULLSCREEN | pygame.NOFRAME if self._fullscreen else 0
        self._screen = pygame.display.set_mode(
            (self._width, self._height), flags
        )
        self._screen.fill((0, 0, 0))
        pygame.display.flip()

        brightness = self._cfg.get('brightness', 1.0)
        if brightness != 1.0:
            _xrandr_brightness(brightness)

    def stop(self):
        pygame.quit()

    @property
    def size(self):
        return (self._width, self._height)

    def show(self, pil_image: Image.Image, transition: str = 'cut'):
        """Display a PIL image. transition: 'cut' or 'fade'."""
        if self._rotation:
            pil_image = pil_image.rotate(-self._rotation, expand=True)

        new_surface = self._pil_to_surface(pil_image)

        if transition == 'fade' and self._current_surface is not None:
            self._fade(self._current_surface, new_surface)
        else:
            self._screen.blit(new_surface, (0, 0))
            pygame.display.flip()

        self._current_surface = new_surface

    def play_video(self, path: str, volume: int = 50, meta: dict = None,
                   stop_flag=None, command_cb=None) -> bool:
        """Play a video using mpv, suspending and restoring pygame.

        meta: per-file framing settings (video_fit, video_pan_x/y, video_zoom, volume).
        stop_flag: callable returning True when playback should be aborted.
        command_cb: callable returning a command string ('next'/'prev') or None.
        Returns True if the video played to completion, False if skipped/error.
        """
        meta = meta or {}
        if meta.get('volume') is not None:
            volume = int(meta['volume'])

        vo_flag = _mpv_vo_flag()
        cmd = [
            'mpv', '--fullscreen', f'--volume={volume}',
            '--no-terminal', '--really-quiet',
        ]
        if vo_flag:
            cmd.append(vo_flag)

        # Framing flags from per-file meta
        fit = meta.get('video_fit', 'fill')
        if fit == 'stretch':
            cmd.append('--video-aspect-override=no')
        elif fit == 'fit':
            pass  # mpv default: letterbox to fit
        else:  # fill (default)
            cmd.append('--panscan=1.0')
            pan_x = float(meta.get('video_pan_x', 0.0))
            pan_y = float(meta.get('video_pan_y', 0.0))
            if pan_x:
                cmd.append(f'--video-pan-x={pan_x:.3f}')
            if pan_y:
                cmd.append(f'--video-pan-y={pan_y:.3f}')

        zoom = float(meta.get('video_zoom', 0.0))
        if zoom:
            cmd.append(f'--video-zoom={zoom:.3f}')

        cmd.append(path)

        pygame.display.quit()
        try:
            proc = subprocess.Popen(cmd)
        except FileNotFoundError:
            _log.warning('mpv not found — install it to play videos: sudo apt install mpv')
            self._reinit_display()
            return False

        try:
            while True:
                ret = proc.poll()
                if ret is not None:
                    return ret == 0
                if stop_flag and stop_flag():
                    proc.terminate()
                    proc.wait()
                    return False
                if command_cb:
                    directive = command_cb()
                    if directive in ('next', 'prev'):
                        proc.terminate()
                        proc.wait()
                        return False
                time.sleep(0.25)
        finally:
            self._reinit_display()

    def _reinit_display(self):
        pygame.display.init()
        pygame.display.set_caption('PiFrame')
        if self._cfg.get('hide_cursor', True):
            pygame.mouse.set_visible(False)
        flags = pygame.FULLSCREEN | pygame.NOFRAME if self._fullscreen else 0
        self._screen = pygame.display.set_mode((self._width, self._height), flags)
        self._screen.fill((0, 0, 0))
        if self._current_surface:
            self._screen.blit(self._current_surface, (0, 0))
        pygame.display.flip()

    def blank(self):
        self._screen.fill((0, 0, 0))
        pygame.display.flip()

    def pump_events(self):
        """Call from the main loop to keep pygame responsive."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                mods = pygame.key.get_mods()
                if mods & pygame.KMOD_CTRL:
                    if event.key == pygame.K_d:
                        pygame.display.iconify()
                    elif event.key == pygame.K_w:
                        self._fullscreen = not self._fullscreen
                        flags = pygame.FULLSCREEN | pygame.NOFRAME if self._fullscreen else 0
                        self._screen = pygame.display.set_mode(
                            (self._width, self._height), flags
                        )
                        if self._current_surface:
                            self._screen.blit(self._current_surface, (0, 0))
                            pygame.display.flip()
        return True

    # ── internals ─────────────────────────────────────────────────────────────

    def _pil_to_surface(self, pil_image: Image.Image) -> pygame.Surface:
        rgb = pil_image.convert('RGB')
        raw = rgb.tobytes()
        surface = pygame.image.frombuffer(raw, rgb.size, 'RGB')
        return surface.convert()

    def _fade(self, old: pygame.Surface, new: pygame.Surface,
               steps: int = 20, fps: int = 30):
        clock = pygame.time.Clock()
        overlay = new.copy()
        for i in range(steps + 1):
            alpha = int(255 * i / steps)
            overlay.set_alpha(alpha)
            self._screen.blit(old, (0, 0))
            self._screen.blit(overlay, (0, 0))
            pygame.display.flip()
            clock.tick(fps)


def _mpv_vo_flag() -> str:
    """Return the right --vo flag for mpv based on the active display server."""
    if os.environ.get('WAYLAND_DISPLAY'):
        return '--vo=gpu'
    if os.environ.get('DISPLAY'):
        return '--vo=gpu'
    # No display server — try DRM (headless / framebuffer Pi)
    return '--vo=drm'


def _xrandr_brightness(brightness: float):
    """Set software brightness on the first connected X11 output."""
    try:
        result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if ' connected' in line:
                output = line.split()[0]
                subprocess.run(['xrandr', '--output', output,
                                '--brightness', f'{brightness:.2f}'],
                               capture_output=True)
                return
    except FileNotFoundError:
        pass
