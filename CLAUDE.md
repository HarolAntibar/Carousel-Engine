# Carousel Engine — Development Guidelines

## Project Overview

Pipeline que transforma un tema o idea cruda en un carrusel visual de 6 slides
(1080x1920 px, 9:16) listo para TikTok e Instagram.

- **Brain:** Python 3.13+, FastAPI — stateless, procesa vía Claude Opus en dos pasos.
- **Image Engine:** fal.ai (`fal-ai/flux-2-pro`) para fondos + PIL/Pillow para texto.
- **Output:** `/carousels/{carousel_id}/slide_1.jpg … slide_6.jpg` en disco local.
- **Interfaces:** HTTP (`POST /generate`) y CLI (`python -m app.cli generate "tema"`).

## Architecture: Separation of Concerns

### Directory Structure

```text
/backend
  /app
    main.py              — FastAPI app, global exception handlers, /health
    cli.py               — CLI local, mismo pipeline que el API (--raw salta el enrich)
    /api
      routes.py          — POST /generate. Thin controller: sin try/except, sin lógica
    /core
      brain.py           — Claude API: enrich → write_slides → plan_visuals → CarouselContent
      prompts.py         — SYSTEM PROMPTS ONLY (VOICE_BIBLE, escritor, director visual)
      schemas.py         — Pydantic V2: contratos de TODO dato que entra o sale
    /image_engine
      generator.py       — Orquesta: 6 Flux en paralelo + composite + save
      flux_client.py     — fal.ai: UNA imagen por llamada, retry con backoff
      compositor.py      — PIL: overlay de título/body sobre el fondo
      templates.py       — Sistema visual: ATMOSPHERE_STYLES, fuentes, canvas 1080x1920
    /config
      settings.py        — pydantic-settings. Única fuente de configuración
  /assets/fronts/Inter   — Fuentes Inter bundleadas (funciona en cualquier OS)

/carousels               — Output runtime: {carousel_id}/slide_1.jpg … slide_6.jpg
```

### Rules

1. **Schemas primero.** Si cambia el contrato con Claude (`prompts.py`) o con el caller
   (`routes.py`), se edita `schemas.py` PRIMERO. Pydantic valida en la frontera —
   data inválida nunca llega a la lógica de negocio ("parse, don't validate").
2. **Prompts viven en `core/prompts.py` únicamente.** Cero strings de prompt inline
   en `brain.py` o `routes.py`.
3. **Config vive en `config/settings.py` únicamente.** Nunca `os.getenv()` en lógica
   de negocio. (Excepción documentada: el bridge `os.environ["FAL_KEY"]` en
   `flux_client.py`, porque `fal_client` lee de `os.environ`.)
4. **Routes son thin controllers.** `routes.py` solo llama servicios en orden y retorna.
   Sin try/except (los errores suben a los handlers globales de `main.py`), sin DB,
   sin prompts. Si una ruta crece en lógica, esa lógica va a un servicio.
5. **Un módulo, una API externa.** `brain.py` solo conoce Anthropic. `flux_client.py`
   solo conoce fal.ai y genera UNA imagen. `generator.py` orquesta múltiples llamadas.
6. **PIL es la capa de texto. Flux es la capa de fondo.** Nunca pedirle texto a Flux —
   falla. FLUX.2 [pro] no acepta negative_prompt: las exclusiones (`text,
   typography, watermark, logo`, CGI, luz plana) viven como reglas NEVER
   INCLUDE en `BRAIN_SYSTEM_PROMPT`.
7. **`templates.py` es el único dueño del look.** `compositor.py` no hardcodea colores,
   fuentes ni tamaños. Cambiar el estilo de una atmosphere = editar solo `templates.py`.
8. **Stateless Brain.** FastAPI no escribe en DB ni guarda estado entre requests.
   El único side-effect permitido es escribir imágenes en `/carousels/`.

## Pipeline: Data Flow

```
POST /generate { topic }          (o python -m app.cli generate)
       │
       ▼
brain.enrich_topic(topic)         — 1ª llamada Claude: expande el tema crudo a
       │                            3–4 frases densas con tensión, consecuencia
       │                            y una escena concreta
       ▼
brain.write_slides(enriched)      — 2ª llamada Claude (EL ESCRITOR): SOLO los 6
       │                            title+body, con VOICE_BIBLE (registro sobrio
       │                            con autoridad, español neutro). Validado con
       │                            SlidesDraft.model_validate()
       ▼
ESCALERA DE VOZ                   — lint Python determinista (_lint_voice: slang
       │                            regional, em dash, exceso de máximas). Si hay
       │                            violaciones → 1 llamada de corrección; si
       │                            persisten → error explícito
       ▼
brain.plan_visuals(enriched,      — 3ª llamada Claude (EL DIRECTOR VISUAL):
       │            slides)         atmosphere, authority_score y 6 flux_prompts
       │                            derivados de los slides YA escritos.
       │                            Validado con VisualPlan.model_validate()
       ▼
GUARD: authority_score            — si score < AUTHORITY_THRESHOLD → RejectedResponse
       │                            y STOP. Un rechazo cuesta 3 llamadas Claude,
       │                            cero llamadas fal.ai
       ▼
generator.generate_carousel()     — 6 llamadas Flux EN PARALELO
       │                            (asyncio.gather + return_exceptions=True)
       ▼
compositor.composite_slide()      — PIL: fondo + texto según atmosphere.
       │                            slide 1 = portada (layout distinto)
       ▼
Guardar JPEG quality=95 → retornar paths absolutos
```

**Por qué tres llamadas a Claude en vez de una:** cada llamada hace una cosa
bien. El mega-prompt anterior hacía que la voz del texto compitiera por
atención con la dirección de arte y el scoring, y la voz siempre perdía.
`process_topic()` sigue siendo la única entrada para routes/cli — internamente
orquesta escritor → escalera de voz → director visual. El costo extra
(centavos) lo vale. Las llamadas principales corren con adaptive thinking —
el texto se extrae con `_extract_text()`, nunca con `content[0]`.

## Visual System

- **8 atmospheres:** `Deep Work`, `Momentum`, `Clarity`, `Brutalism`, `Ember`,
  `Violet`, `Fog`, `Neon`. Definidas como `Literal` en `schemas.py` — si Claude
  devuelve una variante ("deep work", "DeepWork"), la validación falla a propósito.
- **Todo el texto es blanco.** Flux genera fotos oscuras/moody; la diferenciación
  visual viene del estilo de la foto y la tipografía, no del color de texto.
- **Fuentes:** Inter bundleada en `assets/`, con fallbacks de sistema vía
  `FONT_CANDIDATES` (prioridad: Inter → DejaVuSans → Arial).
- **Resolución fija:** 1080x1920 (constantes `IMAGE_WIDTH`/`IMAGE_HEIGHT` en
  `templates.py`). No parametrizable en runtime.
- **`AtmosphereStyle` es frozen dataclass** — inmutable, no se muta un estilo compartido.

## API Contract

### POST /generate

**Request:** `{ "topic": "string (min 10 chars)" }`

**Response 200:**
```json
{
  "slides": [ { "index": 1, "title": "max 50 chars", "body": "max 110 chars" }, ... ],
  "atmosphere": "Deep Work",
  "authority_score": 0.85,
  "image_paths": ["...\\carousels\\{id}\\slide_1.jpg", "..."],
  "enriched_topic": "string"
}
```

**Response 200 (rechazado):** si `authority_score < AUTHORITY_THRESHOLD`, el guard
corta ANTES de generar imágenes. Un rechazo no es un error — el pipeline funcionó,
el contenido no pasó la barra de calidad:
```json
{
  "rejected": true,
  "authority_score": 0.55,
  "atmosphere": "Fog",
  "reason": "authority_score 0.55 is below threshold 0.7"
}
```

| Código | Significado | ¿Reintentar? |
|--------|-------------|--------------|
| 200 + `rejected: true` | Score bajo el threshold — sin imágenes generadas | No — mejorar el topic |
| 422 | Body inválido / topic muy corto (Pydantic automático) | No — corregir input |
| 500 | `BrainProcessingError` — Claude falló o devolvió schema inválido | No — problema nuestro |
| 503 | `FluxGenerationError` — fal.ai caído tras 4 intentos | Sí — upstream temporal |

### GET /health

`{ "status": "ok" }` — para healthchecks y monitores de uptime.

## Code Style

- **Strict typing:** type hints en toda función. Estructuras complejas → modelos
  Pydantic en `schemas.py`, no dicts sueltos.

- **Early returns (obligatorio):** guard clauses primero, happy path al final.
  Nunca nesting de if/else.
  **Excepción:** `else` está OK dentro de loops para control de flujo (ej. word-wrap
  en `compositor.py`) y para asignación multi-rama donde el early return no aplica.
  ```python
  # BIEN
  def composite(text: str) -> Image.Image:
      if not text:
          raise ValueError("text is empty")
      if len(text) > limit:
          text = truncate(text)
      return render(text)
  ```

- **Async por defecto:** todo endpoint FastAPI y toda llamada a API externa
  (Anthropic, fal.ai, httpx) usa `async/await`. Cero llamadas síncronas bloqueantes.

- **Clientes API como singletons a nivel de módulo:** `AsyncAnthropic` se crea una
  vez al importar el módulo (maneja su propio connection pool). Crearlo por request
  es desperdicio.

- **Paths absolutos únicamente:** `Path(...).resolve()` antes de escribir a disco.
  Prohibido `../` en cualquier file operation.

- **Comentarios explican el POR QUÉ**, no el qué. El estilo del repo documenta
  patrones y decisiones (headers de archivo con ROLE/WHY) — mantenerlo.

- Commits tersos y directos. Sin emojis en código.

## Error Handling

### Estrategia: excepciones custom + handlers globales

- Cada servicio define SU excepción: `BrainProcessingError` (brain.py),
  `FluxGenerationError` (flux_client.py). Envuelven los errores del SDK para no
  exponer internals al caller.
- `main.py` registra los `@app.exception_handler` que mapean excepción → HTTP status.
  **`routes.py` no sabe nada de errores** — solo happy path.
- División de responsabilidades: `main.py` sabe QUÉ errores existen y CÓMO responder;
  `brain.py`/`flux_client.py` saben CUÁNDO lanzarlos.

### Zero Silent Failures

```python
# MAL — esconde que Claude devolvió basura
slides = response.get("slides", [])

# BIEN — falla ruidosamente, con el raw response en el log para debugging
logger.error("Schema validation failed: %s. Raw: %s", e, raw_content)
raise BrainProcessingError(...) from e
```

- Pydantic valida TODO output de Claude con `model_validate()`. Schema inválido =
  error explícito con el raw response loggeado, nunca parseo manual ni fallback mudo.
- Flux falla tras retries → `FluxGenerationError`. **Nunca** retornar placeholder
  ni fondo vacío.
- Encadenar siempre con `raise ... from e` para preservar el traceback original.

### Fallbacks: explícitos, no silenciosos

Un fallback es válido solo si está documentado y degrada de forma visible (log):

- **OK:** escalera de corrección de longitud en `brain.py` — si la ÚNICA falla de
  validación es `string_too_long`: (1) retry con prompt de corrección,
  (2) truncado en Python al último word boundary. Ambos pasos loggean `warning`.
  Cualquier otro error de schema falla directo.
- **OK:** escalera de voz en `brain.py` — lint determinista (`_lint_voice`) tras
  el escritor: slang regional, em dash, dos puntos, exceso de máximas simétricas.
  Violación → 1 llamada de corrección selectiva → re-lint. Si persiste, FALLA
  explícita (a diferencia de la longitud, no hay fallback mecánico aceptable
  para el registro: publicar slang rechazado es peor que perder la corrida).
- **OK:** `FONT_CANDIDATES` — cadena de fuentes con prioridad explícita.
- **OK:** strip de fences ```` ```json ```` y `raw_decode()` para JSON con basura
  posterior — casos conocidos del output de Claude, manejados explícitamente.
- **MAL:** `data.get("campo", default)` para ocultar que falta un dato requerido.

### Retry: solo en la frontera con fal.ai

- `flux_client.py`: 4 intentos (inmediato, +1s, +2s, +4s — backoff exponencial).
  Cada retry loggea `warning` con el error anterior.
- `generator.py` usa `asyncio.gather(..., return_exceptions=True)` para que un
  fondo fallido no cancele los otros 5; si alguno falló, el carrusel completo
  falla junto con el conteo (`"2/6 backgrounds failed"`).

### Fail Fast en startup

- `settings.py`: `anthropic_api_key` y `fal_key` no tienen default → la app crashea
  al arrancar si faltan, no a mitad del pipeline con tokens ya gastados.
- Validator extra: key presente pero vacía también falla.

## Configuration

Todo tunable vive en `Settings` (pydantic-settings, prioridad: env var > `.env` > default):

| Variable | Default | Uso |
|----------|---------|-----|
| `ANTHROPIC_API_KEY` | — (requerida) | Claude |
| `FAL_KEY` | — (requerida) | Flux |
| `AUTHORITY_THRESHOLD` | `0.7` | Guard activo: score menor → `RejectedResponse` sin imágenes |
| `CAROUSELS_OUTPUT_DIR` | `./carousels` | Raíz de output |
| `WATERMARK_HANDLE` | `@Harol_antibar` | Marca de agua en la esquina inferior derecha |
| `CLAUDE_MODEL` | `claude-opus-4-8` | Swappable sin tocar código |
| `CLAUDE_MAX_TOKENS` | `8192` | Límite de respuesta (incluye thinking) |

## Don'ts

- **No pedir texto a Flux.** PIL es el único que renderiza texto.
- **No prompts inline.** Todo prompt vive en `core/prompts.py`.
- **No `os.getenv()` en lógica de negocio.** Todo pasa por `settings`.
- **No llamadas síncronas a APIs externas.** Todo es `async`.
- **No nesting de if/else.** Early returns (ver excepción para loops).
- **No asumir que Claude devolvió JSON válido.** Siempre `model_validate()`.
- **No `.get("campo", [])` para esconder data faltante.** Fallar ruidosamente.
- **No retornar placeholders cuando una API externa falla.** Excepción explícita.
- **No hardcodear estilos en `compositor.py`.** Colores/fuentes van en `templates.py`.
- **No hardcodear el threshold de `authority_score`.** Viene de `settings`.
- **No escribir en DB desde FastAPI.** El Brain es stateless; el caller es quien
  gestiona el estado.
- **No over-engineering.** Shippear lo mínimo necesario.
