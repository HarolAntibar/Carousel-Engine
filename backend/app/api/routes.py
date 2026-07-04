# =============================================================================
# FILE: api/routes.py
# ROLE: HTTP route definitions. Translates an HTTP request into a pipeline
#       call and returns the result as an HTTP response.
# =============================================================================
#
# WHY THIS FILE IS INTENTIONALLY THIN
# ------------------------------------
# Routes are infrastructure, not business logic. Their only job is:
#   1. Receive the request (FastAPI + Pydantic handle validation automatically)
#   2. Call the services in order
#   3. Return the response
#
# No try/except here — errors propagate up to the global handlers in main.py.
# No database calls — this service is intentionally stateless.
# No prompt strings — those live in core/prompts.py.
#
# PATTERN: Thin controllers
# If you find yourself writing complex logic inside a route function,
# that logic belongs in a service module (brain.py, generator.py, etc.)
# not here. Routes should read like a table of contents, not a chapter.
#
# HOW FastAPI HANDLES VALIDATION
# -------------------------------
# The `request: GenerateRequest` parameter is automatically validated by
# Pydantic when the request arrives. If the body is malformed or the topic
# is too short, FastAPI returns a 422 Unprocessable Entity before this
# function is even called. Zero manual validation needed.
# =============================================================================

from datetime import datetime

from fastapi import APIRouter

from app.config.settings import settings
from app.core import brain
from app.core.schemas import GenerateRequest, GenerateResponse, RejectedResponse
from app.image_engine import generator


router = APIRouter()


@router.post("/generate")
async def generate(request: GenerateRequest) -> GenerateResponse | RejectedResponse:
    # Timestamp-based ID — simple and sortable. In a multi-instance deployment
    # you'd want a UUID instead to avoid collisions.
    carousel_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Step 1: Enrich the raw topic with tension and specificity.
    # A 5-word topic becomes 3–4 dense sentences — better raw material for Claude.
    enriched = await brain.enrich_topic(request.topic)

    # Step 2: Generate 6 slides + atmosphere + flux prompts from the enriched topic.
    content = await brain.process_topic(enriched)

    # Guard: reject low-quality content BEFORE spending on image generation.
    # This is the ONLY quality gate in the pipeline — a rejection costs 2 Haiku
    # calls (~$0.001) instead of 2 Haiku calls + 6 fal.ai images.
    if content.authority_score < settings.authority_threshold:
        return RejectedResponse(
            authority_score=content.authority_score,
            atmosphere=content.atmosphere,
            reason=(
                f"authority_score {content.authority_score:.2f} is below "
                f"threshold {settings.authority_threshold}"
            ),
        )

    # Step 3: Generate 6 photorealistic backgrounds in parallel, composite text
    # over each one, and save to disk. Returns the list of file paths.
    image_paths = await generator.generate_carousel(content, carousel_id)

    return GenerateResponse(
        slides=content.slides,
        atmosphere=content.atmosphere,
        authority_score=content.authority_score,
        image_paths=image_paths,
        enriched_topic=enriched,
    )
