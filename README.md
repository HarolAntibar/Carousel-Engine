# Content Automation — AI Carousel Engine

Transforms any topic or idea into a polished social media carousel (1080×1920 px) ready for TikTok and Instagram. One API call generates 6 slides with AI-written copy and photorealistic backgrounds.

---

## How It Works

```
POST /generate  { "topic": "..." }
        │
        ▼
Claude enriches the raw topic
(adds tension, specificity, real angle)
        │
        ▼
Claude generates 6 slides
  · title + body per slide
  · atmosphere classification (8 visual styles)
  · authority score (0.0 – 1.0)
  · 6 visual prompts for image generation
        │
        ▼
fal.ai Flux Realism generates 6 backgrounds
in parallel  (1080×1920 px, photorealistic)
        │
        ▼
PIL composites text over each background
· Inter Black for titles
· Subtle dark gradient behind text zone
· @handle watermark
        │
        ▼
6 × 1080×1920 JPGs  →  /carousels/{id}/
```

---

## Stack

| Layer | Technology |
|---|---|
| API | Python 3.13, FastAPI |
| LLM | Claude (Anthropic SDK) |
| Image generation | fal.ai — Flux Realism |
| Text overlay | PIL / Pillow |
| Validation | Pydantic V2 |
| Containerization | Docker |

---

## Visual Atmospheres

Claude automatically classifies each topic into one of 8 visual styles:

| Atmosphere | Tone | Typography |
|---|---|---|
| **Deep Work** | Dark, focused, invisible complexity | Inter Medium |
| **Momentum** | Energetic, progress, results | Inter Bold |
| **Clarity** | Realizations, perspective shifts | Inter Regular |
| **Brutalism** | Hard truths, mistakes, consequences | Inter Black |
| **Ember** | Passion, personal drive, obsession | Inter Bold |
| **Violet** | Creativity, strategy, lifestyle | Inter Medium |
| **Fog** | Honest reflection, slow realizations | Inter Regular |
| **Neon** | Entertainment, gaming, digital life | Inter Bold |

---

## Project Structure

```
├── Dockerfile
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── assets/
│   │   └── fronts/Inter/      — Bundled Inter font family
│   └── app/
│       ├── main.py            — FastAPI entry point + error handlers
│       ├── api/
│       │   └── routes.py      — POST /generate
│       ├── core/
│       │   ├── brain.py       — Claude integration (enrich + generate)
│       │   ├── prompts.py     — All system prompts (single source of truth)
│       │   └── schemas.py     — Pydantic V2 models
│       ├── image_engine/
│       │   ├── generator.py   — Orchestrates 6-image parallel generation
│       │   ├── flux_client.py — fal.ai client with exponential backoff retry
│       │   ├── compositor.py  — PIL text overlay, gradient, centering
│       │   └── templates.py   — Per-atmosphere colors, fonts, sizing
│       └── config/
│           └── settings.py    — Env vars via pydantic-settings
└── carousels/                 — Output images (gitignored)
```

---

## Setup

### Using Docker (recommended)

**1. Configure environment variables**

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` with your API keys:

```env
ANTHROPIC_API_KEY=sk-ant-...
FAL_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:...
```

**2. Build and run**

```bash
docker build -t content-automation .
docker run -p 8000:8000 --env-file backend/.env content-automation
```

### Local development

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

---

## API

### `POST /generate`

Receives a topic or idea, returns 6 slides with generated images.

**Request**
```json
{ "topic": "why senior developers write less code" }
```

**Response `200`**
```json
{
  "enriched_topic": "The most experienced engineers I know...",
  "atmosphere": "Deep Work",
  "authority_score": 0.91,
  "slides": [
    { "index": 1, "title": "Lo que nadie te dice del seniority", "body": "No es sobre cuánto código escribes." },
    { "index": 2, "title": "Menos código, más impacto", "body": "Un senior borra 200 líneas y el sistema se vuelve 3x más rápido." },
    { "index": 3, "title": "El costo invisible", "body": "Cada línea que escribes es deuda. Alguien la leerá, la mantendrá, la romperá." },
    { "index": 4, "title": "La pregunta correcta", "body": "No es ¿cómo lo implemento? Es ¿debería implementarlo?" },
    { "index": 5, "title": "El trabajo real", "body": "Diseñar, decidir, eliminar. El teclado es lo último que usas." },
    { "index": 6, "title": "Escribe menos. Piensa más.", "body": "El código más elegante es el que nunca escribiste." }
  ],
  "image_paths": [
    "/carousels/20260501_143022/slide_1.jpg",
    "/carousels/20260501_143022/slide_2.jpg",
    "/carousels/20260501_143022/slide_3.jpg",
    "/carousels/20260501_143022/slide_4.jpg",
    "/carousels/20260501_143022/slide_5.jpg",
    "/carousels/20260501_143022/slide_6.jpg"
  ]
}
```

**Response `422`** — topic too short (< 10 chars)

**Response `500`** — Claude API failure

**Response `503`** — fal.ai failed after 3 retries

### `GET /health`

```json
{ "status": "ok" }
```

---

## CLI

Generate a carousel directly from the terminal without running the server:

```bash
cd backend
python -m app.cli generate "the real reason your side project never ships"
```

---

## Design Decisions

**Two-step LLM pipeline** — The topic is enriched before slide generation. A raw 5-word idea becomes 3-4 dense sentences with tension and specificity, which consistently produces higher-quality copy than sending the raw input directly.

**Stateless API** — No database. The caller is responsible for state management. This keeps the service simple, testable, and easy to integrate into any orchestration layer.

**PIL for text, Flux for backgrounds** — Flux renders photorealistic scenes but fails when asked to render text. PIL handles all typography with pixel-perfect control. The two layers never overlap responsibilities.

**Parallel image generation** — All 6 Flux calls run concurrently via `asyncio.gather()`. Sequential generation would take 5× longer for no reason.

**Bundled Inter font** — No system font dependency. The Inter family ships inside `assets/` so the output looks identical in Docker, local dev, and CI.

---

## Roadmap

- [x] FastAPI Brain — Claude topic enrichment + slide generation
- [x] 8 visual atmosphere templates
- [x] fal.ai Flux Realism — parallel generation with retry
- [x] PIL compositor — gradient, centering, watermark
- [x] Docker packaging
- [ ] Social publishing — Instagram Graph API, TikTok API
- [ ] Batch generation from a topic list
