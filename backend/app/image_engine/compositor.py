# =============================================================================
# FILE: image_engine/compositor.py
# ROLE: Merge a Flux-generated background with slide text using PIL/Pillow.
#       Produces the final JPEG for each slide.
# =============================================================================
#
# FUNDAMENTAL RULE
# ----------------
# This file NEVER calls any API. It only operates on PIL Image objects in memory.
# All text is rendered HERE — never ask Flux to render text (it always fails).
#
# TWO SLIDE LAYOUTS
# -----------------
# is_portada=True  (slide 1 — cover):
#   Text block centered at 42% height (upper portion).
#   Floating dark gradient wraps just around the text.
#   No separator line between title and body.
#
# is_portada=False (slides 2–6 — content):
#   Text block centered at 58% height (lower portion).
#   Dark gradient fades in from above the text and covers down to the bottom.
#   Short separator line between title and body.
#
# WHY RGBA OVERLAY PATTERN
# -------------------------
# PIL draws text directly onto an image — there's no built-in support for
# semi-transparent text or gradients on a JPEG (which has no alpha channel).
# The solution: convert to RGBA, draw onto a transparent overlay, then
# alpha_composite() merges both layers. Finally convert back to RGB for saving.
# This pattern is used for both the gradient and the text rendering.
#
# WHY NO TEXT STROKE
# ------------------
# The reference design (image_reference.jpeg) uses clean white text with no
# stroke. Readability comes from the dark Flux backgrounds and the subtle
# dark gradient behind the text area, not from stroke effects.
# Stroke was removed because it made text look heavy and cheap on real photos.
#
# TEXT CENTERING — THE bbox[0] CORRECTION
# ----------------------------------------
# PIL's font.getbbox(text) returns (left, top, right, bottom) offsets from the
# draw origin. The actual rendered width is right - left (not just right).
# Some glyphs have a non-zero left bearing (bbox[0] != 0), meaning the ink
# starts slightly to the right of the origin. Without correcting for this,
# centered text can appear slightly off-center.
# Fix: x = (IMAGE_WIDTH - width) // 2 - bbox[0]
# =============================================================================

import logging

from PIL import Image, ImageDraw, ImageFont

from app.image_engine.templates import (
    ATMOSPHERE_STYLES,
    FONT_CANDIDATES,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
)


logger = logging.getLogger(__name__)

_HANDLE            = "@Harol_antibar"
_HANDLE_FONT_SIZE  = 30
_HANDLE_ALPHA      = 160          # 0–255. 160 ≈ 63% opacity — visible but subtle.

# Font sizes per slide type (px)
_PORTADA_TITLE_SIZE = 72
_PORTADA_BODY_SIZE  = 46
_CONTENT_TITLE_SIZE = 56
_CONTENT_BODY_SIZE  = 46

# Vertical gap between the last title line and the first body line (px)
_TITLE_BODY_GAP = 38

# Separator line drawn between title and body on content slides
_SEPARATOR_WIDTH  = 72
_SEPARATOR_HEIGHT = 2

# Line height = font size + extra leading (breathing room between lines)
_CONTENT_TITLE_LH = _CONTENT_TITLE_SIZE + 20   # 76 px
_CONTENT_BODY_LH  = _CONTENT_BODY_SIZE  + 30   # 76 px
_PORTADA_TITLE_LH = _PORTADA_TITLE_SIZE + 22   # 94 px
_PORTADA_BODY_LH  = _PORTADA_BODY_SIZE  + 26   # 72 px

# Extra pixels added between words in body text — mimics a slightly
# justified look that matches the reference design.
_BODY_WORD_SPACING = 3

_PORTADA_PADDING = 44            # Horizontal padding for portada text (px)

# Gradient constants — controls the dark backdrop behind the text area.
_GRADIENT_MAX_ALPHA = 150        # Max opacity of the gradient (0–255). 150 ≈ 59%.
_GRADIENT_FADE_PX   = 240        # Pixels over which the gradient fades from transparent to solid.
_GRADIENT_PADDING   = 60         # Extra space above/below the text block inside the gradient.


# ── Public entry point ────────────────────────────────────────────────────────

def composite_slide(
    background: Image.Image,
    title: str,
    body: str,
    atmosphere: str,
    is_portada: bool = False,
) -> Image.Image:
    style = ATMOSPHERE_STYLES[atmosphere]
    # Always resize to the target canvas in case Flux returned a slightly different size.
    image = background.copy().resize((IMAGE_WIDTH, IMAGE_HEIGHT))
    if is_portada:
        return _render_portada(image, title, body, style)
    return _render_content(image, title, body, style)


# ── Portada (slide 1 — cover) ─────────────────────────────────────────────────

def _render_portada(image: Image.Image, title: str, body: str, style) -> Image.Image:
    title_font = _load_font("black", _PORTADA_TITLE_SIZE)
    body_font  = _load_font("medium", _PORTADA_BODY_SIZE)

    max_w = IMAGE_WIDTH - _PORTADA_PADDING * 2
    title_lines = _wrap_text(title, title_font, max_w)
    body_lines  = _wrap_text(body, body_font, max_w)

    # 42% from the top — text lives in the upper-middle zone of the cover.
    center_y = int(IMAGE_HEIGHT * 0.42)
    total_h  = _block_height(title_lines, _PORTADA_TITLE_LH) + _TITLE_BODY_GAP + _block_height(body_lines, _PORTADA_BODY_LH)

    # RGBA overlay pattern: draw gradient + text on a transparent layer,
    # then alpha_composite onto the photo.
    rgba    = image.convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    # Floating gradient: wraps only around the text block (fades in above, fades out below).
    _draw_text_gradient(draw, center_y, total_h, floating=True)
    _draw_two_level(
        draw, title_lines, body_lines, title_font, body_font,
        _PORTADA_TITLE_LH, _PORTADA_BODY_LH, style.text_color, center_y,
        show_separator=False,
    )

    image = Image.alpha_composite(rgba, overlay).convert("RGB")
    return _draw_handle(image, style.text_color)


# ── Content slides (slides 2–6) ───────────────────────────────────────────────

def _render_content(image: Image.Image, title: str, body: str, style) -> Image.Image:
    title_font = _load_font("black", _CONTENT_TITLE_SIZE)
    body_font  = _load_font(style.font_key, _CONTENT_BODY_SIZE)

    max_w = IMAGE_WIDTH - style.text_padding * 2
    title_lines = _wrap_text(title, title_font, max_w)
    body_lines  = _wrap_text(body, body_font, max_w)

    # 58% from the top — text lives in the lower portion, leaving the photo visible above.
    center_y = int(IMAGE_HEIGHT * 0.58)
    sep_h    = _SEPARATOR_HEIGHT + 4
    total_h  = _block_height(title_lines, _CONTENT_TITLE_LH) + _TITLE_BODY_GAP + sep_h + _block_height(body_lines, _CONTENT_BODY_LH)

    rgba    = image.convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    # Bottom gradient: fades in above the text and covers down to the image edge.
    _draw_text_gradient(draw, center_y, total_h, floating=False)
    _draw_two_level(
        draw, title_lines, body_lines, title_font, body_font,
        _CONTENT_TITLE_LH, _CONTENT_BODY_LH, style.text_color, center_y,
        show_separator=True, body_word_spacing=_BODY_WORD_SPACING,
    )

    image = Image.alpha_composite(rgba, overlay).convert("RGB")
    return _draw_handle(image, style.text_color)


# ── Gradient ──────────────────────────────────────────────────────────────────

def _draw_text_gradient(
    draw: ImageDraw.ImageDraw,
    center_y: int,
    text_height: int,
    floating: bool,
) -> None:
    """Draw a dark gradient behind the text block to ensure readability on any photo.

    floating=True  — portada: gradient wraps around the text (fades in above, fades out below).
    floating=False — content: gradient fades in above the text and covers the rest of the image.
    """
    top    = center_y - text_height // 2 - _GRADIENT_PADDING
    bottom = center_y + text_height // 2 + _GRADIENT_PADDING

    # Fade-in zone: transparent → solid over _GRADIENT_FADE_PX pixels.
    fade_start    = max(0, top - _GRADIENT_FADE_PX)
    fade_height   = top - fade_start
    if fade_height > 0:
        for y in range(fade_start, top):
            progress = (y - fade_start) / fade_height
            alpha = int(_GRADIENT_MAX_ALPHA * progress)
            draw.line([(0, y), (IMAGE_WIDTH, y)], fill=(0, 0, 0, alpha))

    if floating:
        # Portada: solid zone around text only, then fade out below.
        draw.rectangle([(0, top), (IMAGE_WIDTH, bottom)], fill=(0, 0, 0, _GRADIENT_MAX_ALPHA))
        for i in range(_GRADIENT_FADE_PX):
            y = bottom + i
            if y >= IMAGE_HEIGHT:
                break
            alpha = int(_GRADIENT_MAX_ALPHA * (1 - i / _GRADIENT_FADE_PX))
            draw.line([(0, y), (IMAGE_WIDTH, y)], fill=(0, 0, 0, alpha))
    else:
        # Content slides: solid from text top to the bottom of the image.
        draw.rectangle([(0, top), (IMAGE_WIDTH, IMAGE_HEIGHT)], fill=(0, 0, 0, _GRADIENT_MAX_ALPHA))


# ── Text rendering ────────────────────────────────────────────────────────────

def _block_height(lines: list[str], line_height: int) -> int:
    return len(lines) * line_height


def _line_render_width(line: str, font, extra_word_spacing: int) -> int:
    """Calculate the total rendered width of a line, optionally with extra word spacing."""
    if extra_word_spacing == 0:
        bbox = font.getbbox(line) if hasattr(font, "getbbox") else (0, 0, len(line) * 20, 30)
        return bbox[2] - bbox[0]
    words = line.split(" ")
    total = 0
    for i, word in enumerate(words):
        bbox = font.getbbox(word) if hasattr(font, "getbbox") else (0, 0, len(word) * 20, 30)
        total += bbox[2] - bbox[0]
        if i < len(words) - 1:
            sp = font.getbbox(" ") if hasattr(font, "getbbox") else (0, 0, 12, 30)
            total += (sp[2] - sp[0]) + extra_word_spacing
    return total


def _draw_line_rgba(
    draw: ImageDraw.ImageDraw,
    line: str,
    font,
    x: int,
    y: int,
    color: tuple[int, int, int, int],
    extra_word_spacing: int = 0,
) -> None:
    """Draw a single line onto an RGBA overlay. No stroke — clean text on photo."""
    if extra_word_spacing == 0:
        draw.text((x, y), line, font=font, fill=color)
        return

    # Word-by-word rendering with extra spacing between words.
    # This gives the body text a slightly wider, more editorial feel.
    cx = x
    for i, word in enumerate(line.split(" ")):
        draw.text((cx, y), word, font=font, fill=color)
        if i < len(line.split(" ")) - 1:
            bbox = font.getbbox(word) if hasattr(font, "getbbox") else (0, 0, len(word) * 20, 30)
            cx += bbox[2] - bbox[0]
            sp = font.getbbox(" ") if hasattr(font, "getbbox") else (0, 0, 12, 30)
            cx += (sp[2] - sp[0]) + extra_word_spacing


def _draw_two_level(
    draw: ImageDraw.ImageDraw,
    title_lines: list[str],
    body_lines: list[str],
    title_font,
    body_font,
    title_lh: int,
    body_lh: int,
    color: tuple[int, int, int],
    center_y: int,
    show_separator: bool = False,
    body_word_spacing: int = 0,
) -> None:
    """Draw the title block, optional separator, and body block centered at center_y."""
    title_h = _block_height(title_lines, title_lh)
    body_h  = _block_height(body_lines, body_lh)
    sep_h   = _SEPARATOR_HEIGHT + 4 if show_separator else 0
    total_h = title_h + _TITLE_BODY_GAP + sep_h + body_h

    # y is the top edge of the entire text block.
    y = center_y - total_h // 2

    main_color = (*color, 255)     # Fully opaque RGBA

    for line in title_lines:
        w     = _line_render_width(line, title_font, 0)
        # bbox[0] correction: some glyphs have left bearing (ink starts right of origin).
        # Without this, centered text can appear 1–3px off-center.
        bbox0 = title_font.getbbox(line)[0] if hasattr(title_font, "getbbox") else 0
        x     = (IMAGE_WIDTH - w) // 2 - bbox0
        _draw_line_rgba(draw, line, title_font, x, y, main_color)
        y += title_lh

    if show_separator:
        sep_y = y + _TITLE_BODY_GAP // 2 - _SEPARATOR_HEIGHT
        sep_x = (IMAGE_WIDTH - _SEPARATOR_WIDTH) // 2
        draw.rectangle(
            [(sep_x, sep_y), (sep_x + _SEPARATOR_WIDTH, sep_y + _SEPARATOR_HEIGHT)],
            fill=(*color, 220),
        )

    y += _TITLE_BODY_GAP + sep_h

    for line in body_lines:
        w     = _line_render_width(line, body_font, body_word_spacing)
        bbox0 = body_font.getbbox(line)[0] if hasattr(body_font, "getbbox") else 0
        x     = (IMAGE_WIDTH - w) // 2 - bbox0
        _draw_line_rgba(draw, line, body_font, x, y, main_color, extra_word_spacing=body_word_spacing)
        y += body_lh


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_font(font_key: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font by weight key at the given size. Falls back gracefully if file not found."""
    for candidate in FONT_CANDIDATES[font_key]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    # PIL's built-in bitmap font — last resort, looks pixelated at large sizes.
    logger.warning("No font found for key '%s' — falling back to PIL default", font_key)
    return ImageFont.load_default(size=size)


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Break text into lines that fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = font.getbbox(candidate) if hasattr(font, "getbbox") else (0, 0, len(candidate) * 20, 30)
        # Use bbox[2] - bbox[0] (actual ink width), not bbox[2] alone.
        # bbox[0] can be non-zero for strings starting with certain glyphs.
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines


def _draw_handle(image: Image.Image, text_color: tuple[int, int, int]) -> Image.Image:
    """Draw the @handle watermark in the bottom-right corner."""
    rgba    = image.convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    font       = _load_font("regular", _HANDLE_FONT_SIZE)
    main_color = (*text_color, _HANDLE_ALPHA)

    bbox = font.getbbox(_HANDLE) if hasattr(font, "getbbox") else (0, 0, len(_HANDLE) * 15, _HANDLE_FONT_SIZE)
    # 72px margin from the right and bottom edges.
    x = IMAGE_WIDTH - (bbox[2] - bbox[0]) - 72
    y = IMAGE_HEIGHT - 72

    draw.text((x, y), _HANDLE, font=font, fill=main_color)

    return Image.alpha_composite(rgba, overlay).convert("RGB")
