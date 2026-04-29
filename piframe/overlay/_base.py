"""Shared helpers for overlay rendering."""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

_PADDING = 16
_LINE_SPACING = 6

# Curated named fonts available on Raspberry Pi OS.
# Value: (filesystem path, human-readable label)
FONT_FAMILIES: dict[str, tuple[str, str]] = {
    'dejavu-bold':       ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',      'DejaVu Sans Bold'),
    'dejavu':            ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',            'DejaVu Sans'),
    'dejavu-serif-bold': ('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',     'DejaVu Serif Bold'),
    'dejavu-serif':      ('/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',          'DejaVu Serif'),
    'dejavu-mono-bold':  ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',  'DejaVu Mono Bold'),
    'dejavu-mono':       ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',       'DejaVu Mono'),
    'freesans-bold':     ('/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',       'Free Sans Bold'),
    'freesans':          ('/usr/share/fonts/truetype/freefont/FreeSans.ttf',           'Free Sans'),
    'freeserif-bold':    ('/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf',      'Free Serif Bold'),
    'freeserif':         ('/usr/share/fonts/truetype/freefont/FreeSerif.ttf',          'Free Serif'),
}

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_FC_FONTS: dict[str, tuple[str, str]] = {}   # key -> (path, label) for fc-list discovered fonts
_FC_SCANNED = False


def _scan_system_fonts():
    """Populate _FC_FONTS once via fc-list, ignoring paths already in FONT_FAMILIES."""
    global _FC_SCANNED
    if _FC_SCANNED:
        return
    _FC_SCANNED = True
    try:
        result = subprocess.run(
            ['fc-list', '--format', '%{file}\n'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return
        known_paths = {path for path, _ in FONT_FAMILIES.values()}
        for line in result.stdout.splitlines():
            p = line.strip()
            if not p or p in known_paths or not p.lower().endswith(('.ttf', '.otf')):
                continue
            key = f'fc:{Path(p).stem}'
            if key not in _FC_FONTS:
                _FC_FONTS[key] = (p, Path(p).stem)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass


def available_fonts() -> list[tuple[str, str]]:
    """Return (key, label) for all available fonts: curated list + fc-list discoveries."""
    _scan_system_fonts()
    curated = [(k, label) for k, (path, label) in FONT_FAMILIES.items() if Path(path).exists()]
    extra = [(k, label) for k, (_, label) in _FC_FONTS.items()]
    return curated + extra


def get_font(size: int, family: str = '') -> ImageFont.FreeTypeFont:
    """Return a PIL font for *family* at *size*, falling back gracefully."""
    key = (family, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    font: ImageFont.FreeTypeFont | None = None

    if family in FONT_FAMILIES:
        try:
            font = ImageFont.truetype(FONT_FAMILIES[family][0], size)
        except (IOError, OSError):
            pass

    if font is None and family in _FC_FONTS:
        try:
            font = ImageFont.truetype(_FC_FONTS[family][0], size)
        except (IOError, OSError):
            pass

    if font is None:
        # Try known paths in priority order until one works
        for path, _ in FONT_FAMILIES.values():
            try:
                font = ImageFont.truetype(path, size)
                break
            except (IOError, OSError):
                continue

    if font is None:
        font = ImageFont.load_default()

    _FONT_CACHE[key] = font
    return font


def parse_color(value) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(int(v) for v in value)
    _names = {'white': (255, 255, 255), 'black': (0, 0, 0)}
    return _names.get(str(value).lower(), (255, 255, 255))


def _text_block_size(draw, lines, fonts):
    """Return (width, height, per-line heights) of the full text block."""
    widths, heights = [], []
    for line, font in zip(lines, fonts):
        bbox = draw.textbbox((0, 0), line, font=font)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])
    total_h = sum(heights) + _LINE_SPACING * (len(lines) - 1)
    return max(widths), total_h, heights


def draw_text_with_bg(
    image: Image.Image,
    lines: list[str],
    fonts: list,
    color: tuple,
    *,
    position: str = 'bottom-right',
    shadow: bool = True,
    bg: bool = True,
    bg_opacity: int = 120,
) -> Image.Image:
    """Composite multi-line text onto *image* at the given anchor position."""
    base = image.copy().convert('RGBA')

    _draw = ImageDraw.Draw(base)
    w, h = base.size
    block_w, block_h, line_heights = _text_block_size(_draw, lines, fonts)

    vert, horiz = position.split('-')
    pad = _PADDING
    if vert == 'top':
        y0 = pad
    elif vert == 'center':
        y0 = (h - block_h) // 2
    else:
        y0 = h - block_h - pad
    if horiz == 'left':
        x0 = pad
    elif horiz == 'right':
        x0 = w - block_w - pad
    else:
        x0 = (w - block_w) // 2

    overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    if bg:
        margin = 10
        odraw.rounded_rectangle(
            [x0 - margin, y0 - margin,
             x0 + block_w + margin, y0 + block_h + margin],
            radius=12,
            fill=(0, 0, 0, bg_opacity),
        )

    if shadow:
        y = y0
        for line, font, lh in zip(lines, fonts, line_heights):
            odraw.text((x0 + 2, y + 2), line, font=font, fill=(0, 0, 0, 160))
            y += lh + _LINE_SPACING

    base = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(base)

    y = y0
    for line, font, lh in zip(lines, fonts, line_heights):
        draw.text((x0, y), line, font=font, fill=color)
        y += lh + _LINE_SPACING

    return base.convert('RGB')
