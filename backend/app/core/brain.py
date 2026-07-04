# =============================================================================
# FILE: core/brain.py
# ROLE: All communication with the Claude API. Turns a topic string into a
#       validated CarouselContent object ready for image generation.
# =============================================================================
#
# THE TWO-STEP PIPELINE
# ---------------------
# 1. enrich_topic()  — takes the raw user input and expands it.
#    A 5-word topic like "procrastination" becomes 3–4 sentences with real
#    tension, consequence, and specificity. Better input → better slides.
#
# 2. process_topic() — takes the enriched text and generates the full carousel:
#    6 slides (title + body each), atmosphere, authority score, flux prompts.
#    Output is strictly validated against CarouselContent via Pydantic.
#
# WHY TWO SEPARATE API CALLS INSTEAD OF ONE
# ------------------------------------------
# Combining both steps into one prompt degrades quality. When Claude has to
# simultaneously "understand the topic deeply" AND "format a strict JSON
# schema", it shortcuts the understanding part. Separating them lets each
# call do one thing well. The extra API cost (~$0.001) is worth it.
#
# ERROR HANDLING STRATEGY
# -----------------------
# All Claude API errors are wrapped in BrainProcessingError. This custom
# exception type lets main.py return a 500 with a clear message without
# exposing Anthropic SDK internals to the caller.
#
# PATTERN: Fail loudly on bad data
# Claude occasionally returns JSON that doesn't match the schema. We never
# try to "fix" it silently — we log the raw response and raise an error.
# Exception: if the only issue is text being slightly too long, we retry
# with a correction prompt before falling back to Python truncation.
# =============================================================================

import json
import logging

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config.settings import settings
from app.core.prompts import BRAIN_SYSTEM_PROMPT, SLIDE_LENGTH_CORRECTION_PROMPT, TOPIC_ENRICHMENT_PROMPT
from app.core.schemas import CarouselContent


class BrainProcessingError(Exception):
    pass


logger = logging.getLogger(__name__)

# The Anthropic client is created once at module load time.
# AsyncAnthropic uses httpx under the hood and manages its own connection pool —
# creating it per-request would be wasteful. Module-level singletons are the
# standard pattern for API clients in Python async applications.
try:
    _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
except Exception as e:
    raise RuntimeError(f"Failed to initialize Anthropic client — check ANTHROPIC_API_KEY: {e}") from e


async def enrich_topic(raw_topic: str) -> str:
    """Expand a raw topic into 2–4 dense sentences with tension and specificity."""
    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=512,
            system=TOPIC_ENRICHMENT_PROMPT,
            messages=[{"role": "user", "content": raw_topic}],
        )
    except Exception as e:
        logger.error("Topic enrichment API call failed: %s", e)
        raise BrainProcessingError(f"Topic enrichment failed: {e}") from e

    enriched = response.content[0].text.strip()
    logger.info("Topic enriched: %d → %d chars", len(raw_topic), len(enriched))
    return enriched


async def process_topic(topic: str) -> CarouselContent:
    """Generate a full carousel from an enriched topic. Returns a validated CarouselContent."""
    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            system=BRAIN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": topic}],
        )
    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        raise BrainProcessingError(f"Claude API call failed: {e}") from e

    raw_content = response.content[0].text
    stripped = _strip_markdown_fences(raw_content)

    # raw_decode() parses the FIRST complete JSON object in the string and
    # ignores anything after it. This handles cases where Claude appends an
    # extra closing brace or a stray comment after the JSON object.
    try:
        data, _ = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError as e:
        logger.error("Claude returned invalid JSON. Raw: %s", raw_content)
        raise BrainProcessingError(f"Claude returned invalid JSON: {e}\nRaw: {raw_content}") from e

    # Validate the parsed dict against the CarouselContent schema.
    # If only text-length fields are over the limit, attempt an automatic
    # correction before giving up — this avoids failing the whole pipeline
    # over a slide that's 5 characters too long.
    try:
        return CarouselContent.model_validate(data)
    except ValidationError as e:
        length_errors = [err for err in e.errors() if err["type"] == "string_too_long"]
        if length_errors and len(length_errors) == len(e.errors()):
            logger.warning("%d field(s) over limit — retrying correction", len(length_errors))
            data = await _fix_slide_lengths(data, length_errors)
            try:
                return CarouselContent.model_validate(data)
            except ValidationError:
                # Correction prompt also failed — truncate in Python as last resort.
                logger.warning("Correction retry failed — applying Python truncation")
                data = _truncate_slides(data)
                return CarouselContent.model_validate(data)

        logger.error("Schema validation failed: %s. Raw: %s", e, raw_content)
        raise BrainProcessingError(f"Claude response failed schema validation: {e}") from e


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` fences if Claude wrapped its JSON output in them.

    This happens occasionally even when the prompt says not to. It's handled
    explicitly because a fence is a KNOWN quirk of model output — not missing
    data being silently papered over.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = "\n".join(stripped.splitlines()[1:])
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    return stripped


# Field limits mirror the Pydantic constraints in schemas.py.
# Defined here (not imported) to keep this module self-contained for the correction logic.
_FIELD_LIMITS = {"title": 50, "body": 110}


async def _fix_slide_lengths(data: dict, errors: list[dict]) -> dict:
    """Ask Claude to rewrite only the fields that exceed their character limit."""
    offending_lines = []
    for err in errors:
        slide_idx = err["loc"][1]
        field = err["loc"][2]
        slide = data["slides"][slide_idx]
        value = slide[field]
        limit = _FIELD_LIMITS.get(field, 110)
        offending_lines.append(
            f'  slide {slide["index"]} {field} ({len(value)} chars, limit {limit}): "{value}"'
        )

    correction_prompt = SLIDE_LENGTH_CORRECTION_PROMPT.format(
        offending_slides="\n".join(offending_lines)
    )

    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=512,
            # No system prompt here — the correction prompt is fully self-contained.
            messages=[{"role": "user", "content": correction_prompt}],
        )
    except Exception as e:
        raise BrainProcessingError(f"Slide length correction API call failed: {e}") from e

    raw = _strip_markdown_fences(response.content[0].text)

    try:
        corrections: dict[str, str] = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BrainProcessingError(f"Slide length correction returned invalid JSON: {e}") from e

    # Apply corrections. Keys are "{slide_index}_{field}" e.g. "2_body", "1_title".
    for slide in data["slides"]:
        for field in ("title", "body"):
            corrected = corrections.get(f'{slide["index"]}_{field}')
            if corrected:
                slide[field] = corrected

    logger.info("Slide length correction applied: %s", list(corrections.keys()))
    return data


def _truncate_slides(data: dict) -> dict:
    """Hard truncation fallback — cuts at the last word boundary before the limit."""
    for slide in data["slides"]:
        for field, limit in _FIELD_LIMITS.items():
            text = slide.get(field, "")
            if len(text) <= limit:
                continue
            cut = text[:limit]
            last_space = cut.rfind(" ")
            # Cut at the last space to avoid breaking mid-word.
            # Strip trailing punctuation that would look odd at a cut point.
            slide[field] = cut[:last_space].rstrip(".,;:") if last_space > 0 else cut
            logger.warning("Slide %d %s truncated to %d chars", slide["index"], field, len(slide[field]))
    return data
