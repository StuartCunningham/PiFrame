"""Overlay that shows photo filename and/or EXIF date taken."""
import os
from datetime import datetime
from PIL import Image

try:
    import piexif
    _PIEXIF = True
except ImportError:
    _PIEXIF = False

from ._base import get_font, parse_color, draw_text_with_bg


def _exif_date(path: str) -> str | None:
    if not _PIEXIF:
        return None
    try:
        exif = piexif.load(path)
        raw = exif.get('Exif', {}).get(piexif.ExifIFD.DateTimeOriginal)
        if raw:
            dt = datetime.strptime(raw.decode(), '%Y:%m:%d %H:%M:%S')
            return dt.strftime('%-d %B %Y')
    except Exception:
        pass
    return None


class PhotoInfoOverlay:
    def __init__(self, config):
        self._config = config

    def draw(self, image: Image.Image, photo_path: str = '') -> Image.Image:
        cfg = self._config.overlays['photo_info']
        lines = []

        if cfg.get('show_date_taken') and photo_path:
            date_str = _exif_date(photo_path)
            if date_str:
                lines.append(date_str)

        if cfg.get('show_filename') and photo_path:
            lines.append(os.path.basename(photo_path))

        if not lines:
            return image

        family = cfg.get('font') or self._config.get('fonts', 'global', default='dejavu-bold')
        font = get_font(cfg['font_size'], family)
        color = parse_color(cfg['color'])

        return draw_text_with_bg(
            image, lines, [font] * len(lines), color,
            position=cfg['position'],
            shadow=cfg.get('shadow', True),
            bg=cfg.get('background', False),
            bg_opacity=cfg.get('background_opacity', 120),
        )
