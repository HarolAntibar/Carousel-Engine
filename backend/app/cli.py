# =============================================================================
# FILE: app/cli.py
# ROLE: Command-line interface for generating carousels without running the
#       HTTP server. Useful for testing and local development.
# =============================================================================
#
# USAGE
#   python -m app.cli generate
#   python -m app.cli generate "why senior developers write less code"
#   python -m app.cli generate "already detailed topic" --raw
#
# PIPELINE PARITY WITH THE API
# ----------------------------
# The CLI runs the SAME pipeline as POST /generate: enrich → process → guard →
# images. One pipeline, predictable behavior — a carousel generated via CLI is
# identical to one generated via HTTP.
# The --raw flag skips the enrichment step, for when you want to test a topic
# that is already detailed (the enrichment would just add noise on top).
#
# WHY THE IMPORTS ARE INSIDE THE FUNCTION
# -----------------------------------------
# Importing brain and generator at the top of the file would trigger
# settings = Settings() inside settings.py at import time. If the .env file
# is missing, the app would crash before printing the usage message.
# Moving the imports inside _generate() means the CLI can at least show
# usage info even if the environment isn't configured.
#
# PATTERN: asyncio.run()
# -----------------------
# FastAPI handles the async event loop automatically. In a plain Python script,
# you need to create and run the event loop yourself. asyncio.run() does that —
# it creates a new event loop, runs the coroutine until it completes, and closes
# the loop. Never call asyncio.run() inside an async function (use await instead).
#
# EXIT CODES
# ----------
# 0 — carousel generated successfully
# 1 — error (Claude failed, Flux failed, invalid usage)
# 2 — content rejected by the authority_score guard (not an error: the
#     pipeline worked, the content just didn't meet the quality bar)
# =============================================================================

import asyncio
import logging
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


async def _generate(topic: str, raw: bool = False) -> None:
    # Deferred imports — see note above about why these are not at the top level.
    from app.config.settings import settings
    from app.core import brain
    from app.core.brain import BrainProcessingError
    from app.image_engine import generator
    from app.image_engine.flux_client import FluxGenerationError

    print(f"\nTopic: {topic}")

    enriched = topic
    if not raw:
        print("Enriching topic with Claude...")
        try:
            enriched = await brain.enrich_topic(topic)
        except BrainProcessingError as e:
            print(f"\n[ERROR] Topic enrichment failed: {e}")
            sys.exit(1)
        print(f"Enriched: {enriched}")

    print("Generating slides with Claude...")
    try:
        content = await brain.process_topic(enriched)
    except BrainProcessingError as e:
        print(f"\n[ERROR] Claude failed: {e}")
        sys.exit(1)

    print(f"Atmosphere: {content.atmosphere} | Score: {content.authority_score:.2f}")

    # Same guard as POST /generate: reject low-quality content BEFORE spending
    # on image generation (6 fal.ai calls saved per rejection).
    if content.authority_score < settings.authority_threshold:
        print(
            f"\n[REJECTED] Score {content.authority_score:.2f} is below "
            f"threshold {settings.authority_threshold} — no images generated."
        )
        sys.exit(2)

    print("Generating backgrounds with Flux...")

    carousel_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        image_paths = await generator.generate_carousel(content, carousel_id)
    except FluxGenerationError as e:
        print(f"\n[ERROR] Flux failed: {e}")
        sys.exit(1)

    print("\n[OK] Carousel generated:")
    for path in image_paths:
        print(f"  {path}")


def cmd_generate(topic: str = "", raw: bool = False) -> None:
    if not topic:
        topic = input("\nWhat is the topic or idea for the carousel?\n> ").strip()
    if not topic:
        print("Error: topic cannot be empty.")
        sys.exit(1)
    asyncio.run(_generate(topic, raw))


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] != "generate":
        print('Usage: python -m app.cli generate ["optional topic"] [--raw]')
        sys.exit(1)

    raw_flag = "--raw" in args
    topic_arg = " ".join(a for a in args[1:] if a != "--raw")
    cmd_generate(topic_arg, raw_flag)
