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
    text_color: tuple[int, int, int]     # RGB text color — all atmospheres use white for dark photo contrast

    # font_key: logical name resolved to a file path via FONT_CANDIDATES below.
    # Using a key (not a path) keeps templates.py decoupled from file system details.
    font_key: str

    text_padding: int = 80               # Horizontal margin from image edge to text (px)


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
        text_color=(255, 255, 255),
        font_key="medium",
        text_padding=48,
    ),

    # Momentum: energy and progress. Bold weight — velocity.
    "Momentum": AtmosphereStyle(
        text_color=(255, 255, 255),
        font_key="bold",
        text_padding=52,
    ),

    # Clarity: realizations and perspective shifts. Regular weight — open, breathable.
    "Clarity": AtmosphereStyle(
        text_color=(255, 255, 255),
        font_key="regular",
        text_padding=64,
    ),

    # Brutalism: hard truths. Black weight — maximum visual impact.
    "Brutalism": AtmosphereStyle(
        text_color=(255, 255, 255),
        font_key="black",
        text_padding=44,
    ),

    # Ember: passion and personal obsession. Bold weight — warm intensity.
    "Ember": AtmosphereStyle(
        text_color=(255, 255, 255),
        font_key="bold",
        text_padding=50,
    ),

    # Violet: creativity and strategy. Medium weight — elevated tone.
    "Violet": AtmosphereStyle(
        text_color=(255, 255, 255),
        font_key="medium",
        text_padding=50,
    ),

    # Fog: honest reflection. Regular weight — slow, soft, introspective.
    "Fog": AtmosphereStyle(
        text_color=(255, 255, 255),
        font_key="regular",
        text_padding=60,
    ),

    # Neon: entertainment and digital culture. Bold weight — fast and loud.
    "Neon": AtmosphereStyle(
        text_color=(255, 255, 255),
        font_key="bold",
        text_padding=48,
    ),
}


# ── Canvas dimensions ────────────────────────────────────────────────────────

# 1080×1920 = 9:16 aspect ratio — the standard for TikTok and Instagram Reels/Stories.
# These are imported by both flux_client.py (image generation size) and
# compositor.py (canvas operations).
IMAGE_WIDTH  = 1080
IMAGE_HEIGHT = 1920
