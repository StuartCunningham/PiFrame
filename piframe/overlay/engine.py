"""Composites all enabled overlays onto a PIL image."""
from PIL import Image

from .clock import ClockOverlay
from .weather import WeatherOverlay
from .photo_info import PhotoInfoOverlay
from ._base import get_font, parse_color, draw_text_with_bg


class OverlayEngine:
    def __init__(self, config, state):
        self._config = config
        self._state = state
        self._clock = ClockOverlay(config)
        self._weather = WeatherOverlay(config, state)
        self._info = PhotoInfoOverlay(config)

    def apply(self, image: Image.Image, photo_path: str = '',
              meta: dict | None = None) -> Image.Image:
        """Apply all enabled overlays and return the composited image."""
        cfg = self._config.overlays
        meta = meta or {}

        if cfg['clock']['enabled']:
            image = self._clock.draw(image)

        if cfg['weather']['enabled']:
            image = self._weather.draw(image)

        if cfg['photo_info']['enabled']:
            image = self._info.draw(image, photo_path)

        caption = (meta.get('caption') or '').strip()
        if caption:
            global_font = self._config.get('fonts', 'global', default='dejavu-bold')
            font = get_font(meta.get('caption_font_size', 36), global_font)
            color = parse_color(meta.get('caption_color', [255, 255, 255]))
            position = meta.get('caption_position', 'bottom-center')
            image = draw_text_with_bg(
                image, [caption], [font], color,
                position=position,
                shadow=True,
                bg=True,
                bg_opacity=140,
            )

        return image
