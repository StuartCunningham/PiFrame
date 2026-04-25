"""HDMI display driver using pygame."""
import os
import pygame
from PIL import Image


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
