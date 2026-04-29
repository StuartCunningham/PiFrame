"""Composites all enabled overlays onto a PIL image."""
import os
from datetime import datetime
from PIL import Image

from .clock import ClockOverlay
from .weather import WeatherOverlay
from .photo_info import PhotoInfoOverlay
from ._base import get_font, parse_color, draw_text_with_bg

_CACHE_MAX = 2


class OverlayEngine:
    def __init__(self, config, state):
        self._config = config
        self._state = state
        self._clock = ClockOverlay(config)
        self._weather = WeatherOverlay(config, state)
        self._info = PhotoInfoOverlay(config)
        self._cache: dict = {}

    def apply(self, image: Image.Image, photo_path: str = '',
              meta: dict | None = None) -> Image.Image:
        """Apply all enabled overlays and return the composited image."""
        cfg = self._config.overlays
        meta = meta or {}

        cache_key = None
        if photo_path and any(cfg[k]['enabled'] for k in ('clock', 'weather', 'photo_info')):
            try:
                mtime_ns = os.stat(photo_path).st_mtime_ns
                clock_min = (datetime.now().strftime('%Y-%m-%dT%H:%M')
                             if cfg['clock']['enabled'] else '')
                cache_key = (photo_path, mtime_ns, clock_min)
                if cache_key in self._cache:
                    return self._cache[cache_key]
            except OSError:
                pass

        result = image

        if cfg['clock']['enabled']:
            result = self._clock.draw(result)

        if cfg['weather']['enabled']:
            result = self._weather.draw(result)

        if cfg['photo_info']['enabled']:
            result = self._info.draw(result, photo_path)

        caption = (meta.get('caption') or '').strip()
        if caption:
            global_font = self._config.get('fonts', 'global', default='dejavu-bold')
            font = get_font(meta.get('caption_font_size', 36), global_font)
            color = parse_color(meta.get('caption_color', [255, 255, 255]))
            position = meta.get('caption_position', 'bottom-center')
            result = draw_text_with_bg(
                result, [caption], [font], color,
                position=position,
                shadow=True,
                bg=True,
                bg_opacity=140,
            )

        if cache_key is not None:
            if len(self._cache) >= _CACHE_MAX:
                self._cache.clear()
            self._cache[cache_key] = result

        return result
