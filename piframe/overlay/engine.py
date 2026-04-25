"""Composites all enabled overlays onto a PIL image."""
from PIL import Image

from .clock import ClockOverlay
from .weather import WeatherOverlay
from .photo_info import PhotoInfoOverlay


class OverlayEngine:
    def __init__(self, config, state):
        self._config = config
        self._state = state
        self._clock = ClockOverlay(config)
        self._weather = WeatherOverlay(config, state)
        self._info = PhotoInfoOverlay(config)

    def apply(self, image: Image.Image, photo_path: str = '') -> Image.Image:
        """Apply all enabled overlays and return the composited image."""
        cfg = self._config.overlays

        if cfg['clock']['enabled']:
            image = self._clock.draw(image)

        if cfg['weather']['enabled']:
            image = self._weather.draw(image)

        if cfg['photo_info']['enabled']:
            image = self._info.draw(image, photo_path)

        return image
