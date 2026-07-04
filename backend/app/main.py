# =============================================================================
# FILE: main.py
# ROLE: FastAPI application entry point. Wires together routes, global error
#       handlers, and the health check endpoint.
# =============================================================================
#
# WHY GLOBAL ERROR HANDLERS
# -------------------------
# Without them, any unhandled BrainProcessingError or FluxGenerationError
# would bubble up to FastAPI's default handler, which returns a generic 500
# with no useful information. By registering custom handlers here we control
# the exact HTTP status code and response shape for each failure type.
#
# This keeps error-handling logic OUT of routes.py — routes only deal with
# the happy path. Errors are caught at the application boundary.
#
# HTTP STATUS CODES USED
# ----------------------
# 500 → brain error: Claude failed or returned invalid data. Caller cannot
#       retry with the same input — something is wrong on our side.
# 503 → image error: fal.ai is unavailable after retries. The input was valid
#       but the upstream service is down. Caller CAN retry later.
#       (503 = "Service Unavailable" — the standard code for upstream failures)
#
# PATTERN: Separation of concerns
# main.py knows WHAT errors exist and HOW to respond to them.
# brain.py and flux_client.py know WHEN to raise them.
# routes.py knows nothing about errors — it just calls services.
# =============================================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.brain import BrainProcessingError
from app.image_engine.flux_client import FluxGenerationError


app = FastAPI(title="Content Brain API", version="0.2.0")

# Register all route handlers defined in api/routes.py.
# include_router allows splitting routes across multiple files as the API grows.
app.include_router(router)


@app.exception_handler(BrainProcessingError)
async def brain_error_handler(request: Request, exc: BrainProcessingError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error_type": "brain", "detail": str(exc)})


@app.exception_handler(FluxGenerationError)
async def flux_error_handler(request: Request, exc: FluxGenerationError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error_type": "image", "detail": str(exc)})


# Health check endpoint — standard practice for any deployed service.
# Used by load balancers and uptime monitors to verify
# the service is alive. Returns 200 OK if the process is running.
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
