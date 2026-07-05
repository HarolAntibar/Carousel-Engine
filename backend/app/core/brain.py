# =============================================================================
# FILE: core/brain.py
# ROLE: All communication with the Claude API. Turns a topic string into a
#       validated CarouselContent object ready for image generation.
# =============================================================================
#
# THE THREE-STEP PIPELINE
# -----------------------
# 1. enrich_topic()  — expands the raw user input. A 5-word topic becomes
#    3–4 sentences with real tension, consequence, and one concrete scene.
#
# 2. write_slides()  — the WRITER: generates ONLY the 6 title+body pairs,
#    guided by VOICE_BIBLE (calm-authority register, neutral Spanish).
#    After it, a deterministic voice lint runs in Python (_lint_voice):
#    regional slang, em dashes, colons, maxim overdose. Violations trigger
#    ONE correction call; if they persist, the pipeline fails loudly —
#    publishing off-register text is worse than losing the run.
#
# 3. plan_visuals()  — the VISUAL DIRECTOR: atmosphere + authority_score +
#    6 FLUX.2 scene prompts, derived FROM the finished slides.
#
# WHY THREE SEPARATE CALLS INSTEAD OF ONE
# ----------------------------------------
# The same argument that created enrich_topic(): each call does one thing
# well. The old mega-prompt made the voice compete for attention with art
# direction and scoring — and the voice always lost. The extra call (cents)
# is the price of copy that doesn't read AI-made.
#
# ERROR HANDLING STRATEGY
# -----------------------
# All Claude API errors are wrapped in BrainProcessingError. This custom
# exception type lets main.py return a 500 with a clear message without
# exposing Anthropic SDK internals to the caller.
#
# PATTERN: Fail loudly on bad data — with two documented ladders:
#   LENGTH ladder: string_too_long → correction call → Python truncation.
#     Degrading is fine here: a slightly shorter sentence is still on-brand.
#   VOICE ladder:  lint violation → correction call → re-lint → ERROR.
#     No mechanical fallback exists for register: publishing slang the user
#     explicitly rejected is worse than failing the run.
# =============================================================================

import json
import logging
import re

from anthropic import AsyncAnthropic
from anthropic.types import Message
from pydantic import ValidationError

from app.config.settings import settings
from app.core.prompts import (
    SLIDE_LENGTH_CORRECTION_PROMPT,
    SLIDE_WRITER_PROMPT,
    TOPIC_ENRICHMENT_PROMPT,
    VISUAL_DIRECTOR_PROMPT,
    VISUAL_DIRECTOR_USER_TEMPLATE,
    VOICE_CORRECTION_PROMPT,
)
from app.core.schemas import CarouselContent, SlidesDraft, VisualPlan


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


# ── Shared response helpers ───────────────────────────────────────────────────

def _extract_text(response: Message) -> str:
    """Return the first text block of a Claude response.

    With adaptive thinking enabled, thinking blocks precede the text block in
    response.content — indexing content[0] would grab a thinking block.
    """
    for block in response.content:
        if block.type == "text":
            return block.text
    raise BrainProcessingError(
        f"Claude returned no text block (stop_reason={response.stop_reason})"
    )


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


def _parse_json_object(raw_content: str) -> dict:
    """Parse the FIRST complete JSON object in a Claude response.

    raw_decode() ignores anything after the object — Opus occasionally appends
    a stray comment or an extra closing brace after the JSON.
    """
    stripped = _strip_markdown_fences(raw_content)
    try:
        data, _ = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError as e:
        logger.error("Claude returned invalid JSON. Raw: %s", raw_content)
        raise BrainProcessingError(f"Claude returned invalid JSON: {e}\nRaw: {raw_content}") from e
    return data


# ── Step 1: enrichment ────────────────────────────────────────────────────────

async def enrich_topic(raw_topic: str) -> str:
    """Expand a raw topic into 2–4 dense sentences with tension and specificity."""
    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            # Thinking shares this budget with the visible answer — 2048 leaves
            # room for reasoning plus the 2-4 enriched sentences.
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system=TOPIC_ENRICHMENT_PROMPT,
            messages=[{"role": "user", "content": raw_topic}],
        )
    except Exception as e:
        logger.error("Topic enrichment API call failed: %s", e)
        raise BrainProcessingError(f"Topic enrichment failed: {e}") from e

    enriched = _extract_text(response).strip()
    logger.info("Topic enriched: %d → %d chars", len(raw_topic), len(enriched))
    return enriched


# ── Step 2: the writer (+ length ladder) ─────────────────────────────────────

async def write_slides(topic: str) -> SlidesDraft:
    """Write the 6 title+body pairs. Text only — no atmosphere, no visuals."""
    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            thinking={"type": "adaptive"},
            system=SLIDE_WRITER_PROMPT,
            messages=[{"role": "user", "content": topic}],
        )
    except Exception as e:
        logger.error("Slide writer API call failed: %s", e)
        raise BrainProcessingError(f"Slide writer call failed: {e}") from e

    raw_content = _extract_text(response)
    data = _parse_json_object(raw_content)

    # Validate against the schema. If only text-length fields are over the
    # limit, run the length ladder before giving up.
    try:
        return SlidesDraft.model_validate(data)
    except ValidationError as e:
        length_errors = [err for err in e.errors() if err["type"] == "string_too_long"]
        if length_errors and len(length_errors) == len(e.errors()):
            logger.warning("%d field(s) over limit — retrying correction", len(length_errors))
            # The ladder never kills the pipeline: if the correction call
            # itself fails, fall through to Python truncation.
            try:
                data = await _fix_slide_lengths(data, length_errors)
            except BrainProcessingError as fix_error:
                logger.warning("Correction call failed (%s) — applying Python truncation", fix_error)
                return SlidesDraft.model_validate(_truncate_slides(data))
            try:
                return SlidesDraft.model_validate(data)
            except ValidationError:
                logger.warning("Correction retry failed — applying Python truncation")
                return SlidesDraft.model_validate(_truncate_slides(data))

        logger.error("Schema validation failed: %s. Raw: %s", e, raw_content)
        raise BrainProcessingError(f"Slide writer response failed schema validation: {e}") from e


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
            # Mechanical rewrite task — no thinking needed, keep it cheap/fast.
            max_tokens=1024,
            # No system prompt here — the correction prompt is fully self-contained.
            messages=[{"role": "user", "content": correction_prompt}],
        )
    except Exception as e:
        raise BrainProcessingError(f"Slide length correction API call failed: {e}") from e

    raw = _strip_markdown_fences(_extract_text(response))

    # raw_decode: Opus occasionally appends a comment after the JSON object,
    # which strict json.loads() rejects.
    try:
        corrections, _ = json.JSONDecoder().raw_decode(raw)
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


# ── Voice ladder: deterministic lint + selective correction ─────────────────

# Regional slang that breaks the neutral-Spanish register. Word-boundary
# matched, case-insensitive. Kept deliberately unambiguous — polysemous words
# ("tío", "vieja") are excluded to avoid false positives.
_BANNED_WORDS = [
    "compa", "compas", "güey", "wey", "chamba", "pana", "panas", "chévere",
    "vaina", "boludo", "boluda", "órale", "curro", "laburo", "parcero",
    "parcera", "carnal", "chido", "chida", "pibe", "piba", "chaval", "chavala",
]
_BANNED_RE = re.compile(r"\b(" + "|".join(_BANNED_WORDS) + r")\b", re.IGNORECASE)

# The balanced-maxim cadence. One per carousel is punch; more is AI tell.
_MAXIM_RES = [
    re.compile(r"\bno es .{1,60}?[.,] es\b", re.IGNORECASE),
    re.compile(r"\bcuanto m[áa]s .{1,60}? m[áa]s\b", re.IGNORECASE),
]

_FORBIDDEN_OPENINGS = (
    "He visto", "La mayoría de la gente", "Es importante",
    "Recuerda que", "Siempre", "Nunca olvides",
)


def _lint_voice(draft: SlidesDraft) -> dict[str, list[str]]:
    """Deterministic register check — zero cost, runs after every writer call.

    Returns {"<slide_index>_<field>": [reasons]} for every offending field.
    Empty dict = the draft is on-register.
    """
    violations: dict[str, list[str]] = {}

    def flag(slide_index: int, field: str, reason: str) -> None:
        violations.setdefault(f"{slide_index}_{field}", []).append(reason)

    maxim_hits: list[tuple[int, str]] = []
    for slide in draft.slides:
        for field in ("title", "body"):
            text: str = getattr(slide, field)
            # findall (not search): report EVERY slang word in the field, so the
            # correction prompt knows about all of them — fixing only the first
            # would make the post-correction re-lint fail the pipeline.
            for slang in _BANNED_RE.findall(text):
                flag(slide.index, field, f'regional slang "{slang}"')
            if "—" in text:
                flag(slide.index, field, "em dash")
            if ":" in text:
                flag(slide.index, field, "colon")
            if field == "body" and text.startswith(_FORBIDDEN_OPENINGS):
                flag(slide.index, field, "forbidden opening")
            if any(pattern.search(text) for pattern in _MAXIM_RES):
                maxim_hits.append((slide.index, field))

    # The first maxim is allowed (it's punchy once) — flag every extra one.
    for slide_index, field in maxim_hits[1:]:
        flag(slide_index, field, "symmetric maxim (only one allowed per carousel)")

    return violations


async def _fix_voice(data: dict, violations: dict[str, list[str]]) -> dict:
    """Ask Claude to rewrite only the fields that break the voice register."""
    slides_by_index = {slide["index"]: slide for slide in data["slides"]}
    offending_lines = []
    for key, reasons in violations.items():
        slide_index, field = key.split("_", 1)
        value = slides_by_index[int(slide_index)][field]
        offending_lines.append(
            f'  slide {slide_index} {field} (violates: {", ".join(reasons)}): "{value}"'
        )

    correction_prompt = VOICE_CORRECTION_PROMPT.format(
        offending_fields="\n".join(offending_lines)
    )

    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            # Mechanical rewrite task — no thinking needed, keep it cheap/fast.
            max_tokens=1024,
            messages=[{"role": "user", "content": correction_prompt}],
        )
    except Exception as e:
        raise BrainProcessingError(f"Voice correction API call failed: {e}") from e

    raw = _strip_markdown_fences(_extract_text(response))
    try:
        corrections, _ = json.JSONDecoder().raw_decode(raw)
    except json.JSONDecodeError as e:
        raise BrainProcessingError(f"Voice correction returned invalid JSON: {e}") from e

    for slide in data["slides"]:
        for field in ("title", "body"):
            corrected = corrections.get(f'{slide["index"]}_{field}')
            if corrected:
                slide[field] = corrected

    logger.info("Voice correction applied: %s", list(corrections.keys()))
    return data


async def _enforce_voice(draft: SlidesDraft) -> SlidesDraft:
    """Run the voice lint; correct once if needed; fail loudly if it persists.

    Unlike the length ladder, there is no mechanical fallback for register:
    publishing slang the user explicitly rejected is worse than failing.
    """
    violations = _lint_voice(draft)
    if not violations:
        return draft

    logger.warning("Voice lint flagged %d field(s) — retrying correction: %s",
                   len(violations), violations)
    data = await _fix_voice(draft.model_dump(), violations)

    try:
        fixed = SlidesDraft.model_validate(data)
    except ValidationError:
        # A rewrite can overrun length limits — truncation is acceptable here
        # because the register (not the length) was the problem being fixed.
        logger.warning("Voice correction overran length limits — applying Python truncation")
        fixed = SlidesDraft.model_validate(_truncate_slides(data))

    remaining = _lint_voice(fixed)
    if remaining:
        raise BrainProcessingError(f"Voice violations persist after correction: {remaining}")
    return fixed


# ── Step 3: the visual director ───────────────────────────────────────────────

async def plan_visuals(topic: str, draft: SlidesDraft) -> VisualPlan:
    """Classify atmosphere, score the content, and write the 6 FLUX.2 prompts."""
    slides_json = json.dumps(draft.model_dump()["slides"], ensure_ascii=False, indent=2)
    user_content = VISUAL_DIRECTOR_USER_TEMPLATE.format(topic=topic, slides_json=slides_json)

    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            thinking={"type": "adaptive"},
            system=VISUAL_DIRECTOR_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:
        logger.error("Visual director API call failed: %s", e)
        raise BrainProcessingError(f"Visual director call failed: {e}") from e

    raw_content = _extract_text(response)
    data = _parse_json_object(raw_content)

    try:
        return VisualPlan.model_validate(data)
    except ValidationError as e:
        logger.error("Visual plan failed schema validation: %s. Raw: %s", e, raw_content)
        raise BrainProcessingError(f"Visual plan failed schema validation: {e}") from e


# ── Orchestrator ──────────────────────────────────────────────────────────────

async def process_topic(topic: str) -> CarouselContent:
    """Generate a full carousel from an enriched topic.

    Orchestrates writer → voice ladder → visual director. Same signature and
    exception contract as always — routes.py and cli.py are unaffected by the
    internal split.
    """
    draft = await write_slides(topic)
    draft = await _enforce_voice(draft)
    plan = await plan_visuals(topic, draft)

    return CarouselContent(
        slides=draft.slides,
        atmosphere=plan.atmosphere,
        authority_score=plan.authority_score,
        flux_prompts=plan.flux_prompts,
    )
