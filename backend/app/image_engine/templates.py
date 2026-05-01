# =============================================================================
# FILE: image_engine/templates.py
# ROLE: Visual design system. Defines colors, fonts, and sizing for each
#       atmosphere. This is the only file you need to edit to change how
#       a carousel looks.
# =============================================================================
#
# SEPARATION OF CONCERNS
# ----------------------
# compositor.py knows HOW to draw text on an image (positioning, wrapping,
# gradient rendering). This file knows WHAT colors and fonts to use per
# atmosphere. Keeping them separate means:
#   - Changing the look of an atmosphere → edit only this file.
#   - Fixing a rendering bug → edit only compositor.py.
#   - Adding a new atmosphere → add one entry here, zero changes elsewhere.
#
# WHY FROZEN DATACLASS
# --------------------
# @dataclass(frozen=True) makes AtmosphereStyle immutable — its fields cannot
# be changed after creation. This prevents accidental mutation of a style
# that's shared across the application. frozen=True also makes the object
# hashable, which is useful if you ever want to use it as a dict key.
#
# FONT LOADING STRATEGY
# ---------------------
# FONT_CANDIDATES provides a priority list per font weight. compositor.py
# tries each path in order and uses the first one PIL can load.
# The Inter fonts in assets/ are guaranteed to exist (bundled with the repo),
# so the system fallbacks (arial.ttf, DejaVuSans.ttf) should rarely be needed.
# This makes the app work on any OS without requiring font installation.
# =============================================================================

from dataclasses import dataclass
from pathlib import Path


# Absolute path to the bundled Inter fonts.
# Path(__file__) is the path to THIS file (templates.py).
# .parent.parent.parent climbs up to backend/, then descends into assets/.
# Using an absolute path means this works regardless of where the app is
# launched from — a common gotcha in containerized environments.
FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "fronts" / "Inter" / "static"


@dataclass(frozen=True)
class AtmosphereStyle:
    bg_color: tuple[int, int, int]       # RGB fallback background (used if Flux fails)
    text_color: tuple[int, int, int]     # RGB text color — all atmospheres use white for dark photo contrast

    # font_key: logical name resolved to a file path via FONT_CANDIDATES below.
    # Using a key (not a path) keeps templates.py decoupled from file system details.
    font_key: str

    font_size: int = 72                  # Base font size for body text (px)
    text_padding: int = 80               # Horizontal margin from image edge to text (px)

    # Optional gradient definition for bg_color — used for reference/future use.
    bg_gradient: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None


# Priority-ordered font candidates per weight.
# Inter (bundled) → DejaVuSans (common on Linux) → Arial (Windows/Mac fallback).
FONT_CANDIDATES: dict[str, list[str]] = {
    "medium":  [str(FONTS_DIR / "Inter_24pt-Medium.ttf"),  "DejaVuSans.ttf",      "arial.ttf"],
    "bold":    [str(FONTS_DIR / "Inter_24pt-Bold.ttf"),    "DejaVuSans-Bold.ttf", "arialbd.ttf"],
    "regular": [str(FONTS_DIR / "Inter_24pt-Regular.ttf"), "DejaVuSans.ttf",      "arial.ttf"],
    "black":   [str(FONTS_DIR / "Inter_24pt-Black.ttf"),   "DejaVuSans-Bold.ttf", "ariblk.ttf"],
}


# All text colors are white (255, 255, 255) because Flux always generates
# dark/moody photos. Black text on a dark photo is invisible.
# The atmosphere differentiates visually through the Flux image style,
# not through text color.
ATMOSPHERE_STYLES: dict[str, AtmosphereStyle] = {

    # Deep Work: focus and invisible complexity. Medium weight — readable, not aggressive.
    "Deep Work": AtmosphereStyle(
        bg_color=(10, 10, 10),
        text_color=(255, 255, 255),
        font_key="medium",
        font_size=68,
        text_padding=48,
    ),

    # Momentum: energy and progress. Bold weight + blue gradient — velocity.
    "Momentum": AtmosphereStyle(
        bg_color=(26, 26, 46),
        text_color=(255, 255, 255),
        font_key="bold",
        font_size=72,
        text_padding=52,
        bg_gradient=((26, 26, 46), (15, 52, 96)),
    ),

    # Clarity: realizations and perspective shifts. Regular weight — open, breathable.
    "Clarity": AtmosphereStyle(
        bg_color=(250, 250, 250),
        text_color=(255, 255, 255),
        font_key="regular",
        font_size=72,
        text_padding=64,
    ),

    # Brutalism: hard truths. Black weight — maximum visual impact.
    "Brutalism": AtmosphereStyle(
        bg_color=(255, 255, 0),
        text_color=(255, 255, 255),
        font_key="black",
        font_size=80,
        text_padding=44,
    ),

    # Ember: passion and personal obsession. Bold + warm gradient.
    "Ember": AtmosphereStyle(
        bg_color=(18, 10, 6),
        text_color=(255, 255, 255),
        font_key="bold",
        font_size=70,
        text_padding=50,
        bg_gradient=((18, 10, 6), (40, 18, 8)),
    ),

    # Violet: creativity and strategy. Medium weight + purple depth.
    "Violet": AtmosphereStyle(
        bg_color=(18, 8, 32),
        text_color=(255, 255, 255),
        font_key="medium",
        font_size=70,
        text_padding=50,
        bg_gradient=((18, 8, 32), (45, 18, 72)),
    ),

    # Fog: honest reflection. Regular weight — slow, soft, introspective.
    "Fog": AtmosphereStyle(
        bg_color=(220, 220, 218),
        text_color=(255, 255, 255),
        font_key="regular",
        font_size=70,
        text_padding=60,
    ),

    # Neon: entertainment and digital culture. Bold + magenta — fast and loud.
    "Neon": AtmosphereStyle(
        bg_color=(4, 4, 4),
        text_color=(255, 255, 255),
        font_key="bold",
        font_size=72,
        text_padding=48,
    ),
}


# ── Canvas dimensions ────────────────────────────────────────────────────────

# 1080×1920 = 9:16 aspect ratio — the standard for TikTok and Instagram Reels/Stories.
# These are imported by both flux_client.py (image generation size) and
# compositor.py (canvas operations).
IMAGE_WIDTH  = 1080
IMAGE_HEIGHT = 1920
