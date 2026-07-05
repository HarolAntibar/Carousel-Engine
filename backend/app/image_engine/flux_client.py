# =============================================================================
# FILE: image_engine/flux_client.py
# ROLE: Generate ONE photorealistic background image from a text prompt using
#       the fal.ai FLUX.2 [pro] model. Includes retry with exponential backoff.
# =============================================================================
#
# SEPARATION OF CONCERNS
# ----------------------
# This file knows how to talk to ONE external API (fal.ai) and generate ONE
# image. It knows nothing about carousels, slides, or text overlay.
# generator.py is responsible for orchestrating multiple calls to this file.
# If fal.ai changes their API, you only touch this file.
#
# MODEL: fal-ai/flux-2-pro
# ------------------------
# Black Forest Labs' flagship — top-tier photorealism (skin, light, anatomy)
# with strong prompt adherence. Priced per megapixel (~$0.045 per 1080x1920).
# The endpoint is zero-config: it does NOT accept negative_prompt,
# num_inference_steps or guidance_scale. Everything the old negative_prompt
# excluded (text, logos, CGI look, bright flat light) is now enforced as
# NEVER INCLUDE rules in BRAIN_SYSTEM_PROMPT, which writes every prompt.
#
# WHY os.environ IS SET MANUALLY
# --------------------------------
# fal_client reads FAL_KEY directly from os.environ. But pydantic-settings
# loads .env into the `settings` object WITHOUT writing to os.environ.
# The line `os.environ["FAL_KEY"] = settings.fal_key` bridges that gap.
# This is done once at module load time using the already-validated key.
#
# PATTERN: Exponential backoff retry
# ------------------------------------
# Instead of retrying immediately after a failure (which can overwhelm an
# already-struggling API), we wait progressively longer between attempts:
#   Attempt 1: immediate
#   Attempt 2: wait 1 second
#   Attempt 3: wait 2 seconds
#   Attempt 4: wait 4 seconds
# After 4 failures we give up and raise FluxGenerationError.
# This pattern is standard for any code that calls external HTTP APIs.
# =============================================================================

import asyncio
import io
import logging
import os

import httpx
import fal_client
from PIL import Image

from app.config.settings import settings
from app.image_engine.templates import IMAGE_HEIGHT, IMAGE_WIDTH


# Bridge: fal_client reads from os.environ, pydantic-settings does not write there.
os.environ["FAL_KEY"] = settings.fal_key

logger = logging.getLogger(__name__)


class FluxGenerationError(Exception):
    """Raised when all retry attempts for background generation have failed.
    Caught by the global handler in main.py → returns HTTP 503 to the caller."""
    pass


# Wait times between retry attempts (seconds). The first attempt uses 0 (no wait).
# [0, *_BACKOFF_SECONDS] expands to [0, 1, 2, 4] in the loop below.
_BACKOFF_SECONDS = [1, 2, 4]


async def generate_background(prompt: str) -> Image.Image:
    """Generate one background image from a Flux prompt. Returns a PIL Image."""
    last_error: Exception | None = None

    for attempt, wait in enumerate([0, *_BACKOFF_SECONDS]):
        if wait:
            logger.warning("Flux attempt %d failed (%s) — retrying in %ds", attempt, last_error, wait)
            await asyncio.sleep(wait)
        try:
            result = await fal_client.run_async(
                "fal-ai/flux-2-pro",
                arguments={
                    # FLUX.2 [pro] has no negative_prompt — the exclusions
                    # (text/watermarks, bright surfaces that would hide white
                    # text, CGI/stock-photo looks) live in BRAIN_SYSTEM_PROMPT.
                    "prompt": prompt,
                    "image_size": {"width": IMAGE_WIDTH, "height": IMAGE_HEIGHT},
                    "output_format": "jpeg",
                    "enable_safety_checker": False,
                },
            )
            # fal.ai returns a signed URL pointing to the generated image on their CDN.
            # We download it immediately so the rest of the pipeline works with
            # PIL Image objects, not URLs.
            image_url: str = result["images"][0]["url"]
            return await _download_image(image_url)

        except Exception as e:
            last_error = e

    logger.error("Flux failed after %d attempts. Last error: %s", len(_BACKOFF_SECONDS) + 1, last_error)
    raise FluxGenerationError(
        f"Flux failed after {len(_BACKOFF_SECONDS) + 1} attempts: {last_error}"
    ) from last_error


async def _download_image(url: str) -> Image.Image:
    """Download an image from a URL and return it as a PIL Image in RGB mode."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
        # convert("RGB") strips the alpha channel if present — JPEG doesn't support
        # transparency, and all our output files are JPEGs.
        return Image.open(io.BytesIO(response.content)).convert("RGB")
