# =============================================================================
# FILE: image_engine/generator.py
# ROLE: Orchestrator for the full carousel image pipeline. Coordinates
#       6 parallel Flux calls and 6 PIL compositing operations.
# =============================================================================
#
# WHAT THIS FILE DOES
# -------------------
# 1. Calls flux_client.generate_background() for each of the 6 flux prompts.
#    All 6 calls run IN PARALLEL — this is the key optimization here.
# 2. For each slide, calls compositor.composite_slide() to overlay the text
#    from that slide onto its corresponding Flux-generated background.
# 3. Saves each final image as a JPEG and returns the list of file paths.
#
# WHY PARALLEL IMAGE GENERATION MATTERS
# ---------------------------------------
# Each Flux call takes ~5–10 seconds. Sequential generation would take
# 30–60 seconds for 6 images. With asyncio.gather() all 6 run simultaneously,
# so the total wait time is roughly equal to the slowest single call (~10s).
#
# PATTERN: asyncio.gather() with return_exceptions=True
# ------------------------------------------------------
# return_exceptions=True means a failed task returns the Exception object
# instead of immediately cancelling all other tasks. Without it, one Flux
# failure would cancel the other 5 even if they were about to succeed.
# After gather() completes, we check if any result is an exception and
# fail the whole carousel together with a clear count ("2/6 failed").
#
# SLIDE ↔ BACKGROUND PAIRING
# ---------------------------
# zip(content.slides, backgrounds) pairs each SlideItem with its corresponding
# PIL Image. The pairing is positional — slide[0] gets backgrounds[0], etc.
# This works because both lists are produced in the same order (index 1–6).
# =============================================================================

import asyncio
import logging
from pathlib import Path

from PIL import Image

from app.config.settings import settings
from app.core.schemas import CarouselContent
from app.image_engine import compositor, flux_client
from app.image_engine.flux_client import FluxGenerationError


logger = logging.getLogger(__name__)


async def generate_carousel(content: CarouselContent, carousel_id: str) -> list[str]:
    """Generate, composite, and save all 6 carousel images. Returns a list of file paths."""
    output_dir = _prepare_output_dir(carousel_id)
    logger.info("carousel_id=%s | Starting generation → %s", carousel_id, output_dir)

    # Launch all 6 Flux API calls concurrently.
    # return_exceptions=True prevents one failure from cancelling the others.
    results: list[Image.Image | BaseException] = await asyncio.gather(
        *[flux_client.generate_background(prompt) for prompt in content.flux_prompts],
        return_exceptions=True,
    )

    errors = [r for r in results if isinstance(r, BaseException)]
    if errors:
        raise FluxGenerationError(f"{len(errors)}/6 backgrounds failed: {errors[0]}")

    backgrounds: list[Image.Image] = results  # type: ignore[assignment]

    paths: list[str] = []
    for slide, background in zip(content.slides, backgrounds):
        # is_portada=True applies the cover slide layout (larger title, floating gradient).
        # All other slides use the content layout (title + separator + body, bottom gradient).
        final_image = compositor.composite_slide(
            background, slide.title, slide.body, content.atmosphere, is_portada=(slide.index == 1)
        )
        path = output_dir / f"slide_{slide.index}.jpg"
        # quality=95 — high quality JPEG. Going higher has diminishing returns;
        # going lower (e.g. 80) noticeably degrades text sharpness at this resolution.
        final_image.save(path, format="JPEG", quality=95)
        paths.append(str(path))
        logger.info("carousel_id=%s | Saved slide %d", carousel_id, slide.index)

    logger.info("carousel_id=%s | Complete — %d images", carousel_id, len(paths))
    return paths


def _prepare_output_dir(carousel_id: str) -> Path:
    # Path.resolve() converts to an absolute path — avoids any ambiguity about
    # where files are written regardless of the current working directory.
    # mkdir(parents=True) creates intermediate directories if they don't exist.
    # mkdir(exist_ok=True) prevents an error if the directory already exists.
    path = (Path(settings.carousels_output_dir) / carousel_id).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path
