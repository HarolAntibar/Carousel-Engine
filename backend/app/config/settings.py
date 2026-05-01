# =============================================================================
# FILE: config/settings.py
# ROLE: Single source of truth for all configuration and environment variables.
# =============================================================================
#
# WHY THIS FILE EXISTS
# --------------------
# Calling os.getenv("KEY") scattered across files is a maintenance trap:
# rename a variable and you'll miss one. Centralizing all config here means
# one place to look, one place to change.
#
# HOW pydantic-settings WORKS
# ---------------------------
# BaseSettings works like a regular Pydantic model but reads values from:
#   1. Environment variables (os.environ)
#   2. A .env file (configured below)
#   3. Default values defined in the class
# Priority order: env var > .env file > default.
#
# WHY THE APP FAILS AT STARTUP IF A KEY IS MISSING
# -------------------------------------------------
# Fields without a default value (like anthropic_api_key, fal_key) are
# REQUIRED. If they're absent, Pydantic raises a ValidationError before
# any request is processed. This is intentional — it's much better to
# crash loudly at startup than to run for hours and fail mid-pipeline
# after already spending API tokens.
#
# PATTERN: Fail Fast
# Instead of silently returning None or a default for missing secrets,
# this forces the developer to notice the problem immediately.
# =============================================================================

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Tells pydantic-settings where to find the .env file.
    # When running with Docker (--env-file flag), the .env is injected
    # directly into os.environ and this file path is irrelevant.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── Required (no default → app crashes at startup if missing) ────────────

    # Anthropic API key. Get one at: https://console.anthropic.com/settings/keys
    anthropic_api_key: str

    # fal.ai API key for Flux image generation. Get one at: https://fal.ai/dashboard/keys
    fal_key: str

    # ── Optional (have sensible defaults → safe to omit from .env) ───────────

    # Minimum authority score for a carousel to pass through to image generation.
    # Content scoring below this threshold is rejected before any images are generated,
    # saving both fal.ai API calls and time. Tunable without touching code.
    authority_threshold: float = 0.7

    # Root folder where generated carousel images are saved.
    # Structure on disk: {carousels_output_dir}/{carousel_id}/slide_1.jpg ... slide_6.jpg
    carousels_output_dir: str = "./carousels"

    # Claude model to use. Swappable without changing any business logic.
    # claude-haiku is the fastest and cheapest model in the Claude 4 family —
    # ideal for structured JSON generation tasks like this one.
    claude_model: str = "claude-haiku-4-5-20251001"

    # Max tokens Claude is allowed to return. 2048 is enough for 6 slides
    # (title + body each) plus 6 flux prompts with room to spare.
    claude_max_tokens: int = 2048

    # PATTERN: Custom validator
    # @field_validator runs after the type coercion — the value is already a str
    # when it reaches here. Returning the value passes validation; raising
    # ValueError fails it with a clear message.
    @field_validator("anthropic_api_key", "fal_key")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("API key cannot be empty — check your .env file")
        return v


# Module-level singleton. Imported by every other module that needs config:
#   from app.config.settings import settings
#
# Because Python caches module imports, this object is created exactly once
# per process. All modules share the same instance.
settings = Settings()
