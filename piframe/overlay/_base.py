"""Shared helpers for overlay rendering."""
from PIL import Image, ImageDraw, ImageFont

_PADDING = 16
_LINE_SPACING = 6


def get_font(size: int) -> ImageFont.FreeTypeFont:
    """Load a font, falling back to the PIL default if no TTF is available."""
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
        'C:/Windows/Fonts/arial.ttf',
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def parse_color(value) -> tuple:
    if isinstance(value, (list, tuple)):
        return tuple(int(v) for v in value)
    # CSS name fallback
    _names = {'white': (255, 255, 255), 'black': (0, 0, 0)}
    return _names.get(str(value).lower(), (255, 255, 255))


def _text_block_size(draw, lines, fonts):
    """Return (width, height) of the full text block."""
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
    image = image.copy()
    draw = ImageDraw.Draw(image)

    w, h = image.size
    block_w, block_h, line_heights = _text_block_size(draw, lines, fonts)

    # Anchor calculation
    vert, horiz = position.split('-')
    pad = _PADDING

    if vert == 'top':
        y0 = pad
    else:
        y0 = h - block_h - pad

    if horiz == 'left':
        x0 = pad
    elif horiz == 'right':
        x0 = w - block_w - pad
    else:  # center
        x0 = (w - block_w) // 2

    # Semi-transparent background pill
    if bg:
        overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        margin = 10
        odraw.rounded_rectangle(
            [x0 - margin, y0 - margin,
             x0 + block_w + margin, y0 + block_h + margin],
            radius=12,
            fill=(0, 0, 0, bg_opacity),
        )
        image = image.convert('RGBA')
        image = Image.alpha_composite(image, overlay).convert('RGB')
        draw = ImageDraw.Draw(image)

    # Draw text lines
    y = y0
    for line, font, lh in zip(lines, fonts, line_heights):
        if shadow:
            draw.text((x0 + 2, y + 2), line, font=font, fill=(0, 0, 0, 160))
        draw.text((x0, y), line, font=font, fill=color)
        y += lh + _LINE_SPACING

    return image
