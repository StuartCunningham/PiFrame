"""Clock and date overlay."""
from datetime import datetime
from PIL import Image

from ._base import get_font, parse_color, draw_text_with_bg


class ClockOverlay:
    def __init__(self, config):
        self._config = config

    def draw(self, image: Image.Image) -> Image.Image:
        cfg = self._config.overlays['clock']
        family = cfg.get('font') or self._config.get('fonts', 'global', default='dejavu-bold')

        now = datetime.now()
        time_str = now.strftime(cfg['time_format'])
        date_fmt = cfg.get('date_format', '')
        date_str = now.strftime(date_fmt) if cfg.get('show_date') and date_fmt else ''

        lines = [time_str]
        if date_str:
            lines.append(date_str)

        font_large = get_font(cfg['font_size'], family)
        font_small = get_font(max(20, cfg['font_size'] - 14), family)
        fonts = [font_large] + [font_small] * (len(lines) - 1)
        color = parse_color(cfg['color'])

        return draw_text_with_bg(
            image, lines, fonts, color,
            position=cfg['position'],
            shadow=cfg.get('shadow', True),
            bg=cfg.get('background', True),
            bg_opacity=cfg.get('background_opacity', 120),
        )
