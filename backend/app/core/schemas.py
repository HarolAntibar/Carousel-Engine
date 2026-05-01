# =============================================================================
# FILE: core/schemas.py
# ROLE: Data contracts — defines the exact shape of every object that travels
#       through the pipeline, from the HTTP request to the final response.
# =============================================================================
#
# WHY THIS FILE IS THE MOST IMPORTANT IN THE PROJECT
# ---------------------------------------------------
# Every piece of data that enters or leaves the system passes through one of
# these models. Pydantic validates automatically on instantiation — if Claude
# returns a field with the wrong type or a missing key, the error is raised
# HERE before any business logic runs on bad data.
#
# RULE: if you change the contract with Claude (prompts.py) or the API
# contract with callers (routes.py), edit THIS FILE FIRST.
#
# PATTERN: Parse, don't validate
# Instead of writing if/else checks throughout the code ("is this field
# present? is this number in range?"), we define the valid shape once and
# let Pydantic enforce it everywhere. Invalid data never reaches business logic.
#
# HOW Pydantic V2 FIELD CONSTRAINTS WORK
# ---------------------------------------
# Field(min_length=6, max_length=6) on a list → exactly 6 items required.
# Field(ge=0.0, le=1.0) on a float → must be between 0.0 and 1.0 inclusive.
# Field(max_length=50) on a str → string cannot exceed 50 characters.
# Violating any constraint raises a ValidationError with a clear message.
# =============================================================================

from typing import Literal

from pydantic import BaseModel, Field


# Literal type — only these exact string values are valid for atmosphere.
# If Claude returns "deep work" (lowercase) or "DeepWork", validation fails.
# This strictness is intentional: it forces Claude to use exact values and
# makes it easy to map atmospheres to visual styles in templates.py.
Atmosphere = Literal["Deep Work", "Momentum", "Clarity", "Brutalism", "Ember", "Violet", "Fog", "Neon"]


# ── Inbound ──────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    # The raw topic from the caller. min_length=10 prevents trivially short inputs
    # like "hi" that would produce meaningless carousels.
    topic: str = Field(min_length=10)


# ── Internal (Claude output) ──────────────────────────────────────────────────

class SlideItem(BaseModel):
    # index: 1 = portada (cover), 2–6 = content slides.
    index: int = Field(ge=1, le=6)

    # title: the bold anchor line rendered in Inter Black at the top of the slide.
    # 50 chars fits ~2 lines at 56pt on a 1080px canvas.
    title: str = Field(max_length=50)

    # body: the insight text rendered below the title.
    # 110 chars fits ~3 lines at 46pt — enough for 1–2 sentences.
    body: str = Field(max_length=110)


class CarouselContent(BaseModel):
    # Exactly 6 slides: 1 portada + 5 content slides.
    slides: list[SlideItem] = Field(min_length=6, max_length=6)

    atmosphere: Atmosphere

    # Claude self-scores the content quality. Scores below settings.authority_threshold
    # could be used to reject low-quality content before spending on image generation.
    authority_score: float = Field(ge=0.0, le=1.0)

    # One visual scene description per slide, passed to Flux for background generation.
    # These are plain English descriptions — Flux never renders text (it fails at that).
    flux_prompts: list[str] = Field(min_length=6, max_length=6)


# ── Outbound ─────────────────────────────────────────────────────────────────

class GenerateResponse(BaseModel):
    slides: list[SlideItem]
    atmosphere: Atmosphere
    authority_score: float = Field(ge=0.0, le=1.0)

    # Absolute paths to the 6 saved JPEG files on disk.
    image_paths: list[str] = Field(min_length=6, max_length=6)

    # The enriched version of the original topic — useful for debugging
    # and for understanding what Claude actually processed.
    enriched_topic: str
