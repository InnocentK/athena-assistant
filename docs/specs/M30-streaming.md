# M30 — Streaming — SPEC (→ 3.0.0)

**Status: specced, ready to implement. THE major release: streaming changes
the `/chat` response contract, which is why it is 3.0.0 and not 2.9.5.**
Must ship atomically — one milestone, one version, all surfaces together.

## Shape

Responses render as they are generated on both surfaces, for the transports
that can stream; everything else degrades honestly to today's buffered
behavior (the M27.1 "unavailable" pattern applied to delivery).

### 1. Adapters — `complete_stream()` (API transports only)
- `chatgpt`, `grok` (api path), `ollama` gain
  `complete_stream(messages, system_prompt) -> Iterator[str | ProviderResponse]`:
  OpenAI SDK `stream=True`; yield each chunk's `choices[0].delta.content`
  text as it arrives; **finish by yielding the final `ProviderResponse`**
  (assembled full content; usage best-effort — the SDK surfaces usage on
  streams only with `stream_options={"include_usage": True}` where the
  backend supports it; absent usage stays absent, never fabricated).
- Defensive: any error mid-stream yields a failure `ProviderResponse` (same
  error strings as today's `complete()`); timeout/bounding config identical
  (`timeout=…, max_retries=0` — INVARIANTS "API adapters must be bounded").
- CLI adapters (claude/gemini/grok-cli/hermes): **no streaming** — a
  subprocess's answer arrives whole. Base class advertises
  `supports_streaming() -> bool` (default False).

### 2. Router — `route_stream()`
- Same attempt loop/order/diagnostics as `route()` (shared internals — do
  NOT fork the routing logic; extract the per-attempt bookkeeping if needed):
  a generator yielding `("chunk", text)` items for streaming-capable
  adapters, then `("done", ProviderResponse)`; for non-streaming adapters:
  buffered `complete()` → one `("chunk", full_text)` + `("done", …)`.
- `on_attempt` (M27.0) fires exactly as before. The M22 trace is completed
  and attached to the final response the same way (`_finalize_trace`).
- Measure-only guarantees unchanged: diagnostics/usage/status can never
  perturb routing.

### 3. HTTP — `POST /chat/stream` (SSE)
- `StreamingResponse` media-type `text/event-stream`; events:
  `event: chunk` `data: {"text": …}` per chunk, then `event: done`
  `data: {provider, model, success, conversation_id, diagnostics}`.
- History (M29.1) + memory (M29.0 cores) run on completion exactly as
  `/chat` does; `conversation_id` semantics identical (validated, created
  when absent). The buffered `POST /chat` **remains, unchanged**, as the
  compatibility surface (and the UI's fallback).
- The route runs the sync generator via a thread → async bridge
  (iterator in `asyncio.to_thread` steps or an `anyio`-safe pattern), so the
  loop stays responsive (M26.5 discipline). `_ROUTE_TIMEOUT` caps the total.

### 4. Web UI
- `sendMessage` posts to `/chat/stream` and reads the SSE body via
  `fetch` + `ReadableStream`; the assistant bubble is created on the first
  chunk and its `textContent` grows incrementally (still XSS-safe);
  diagnostics/usage render from the `done` event; history/`conversation_id`
  threading unchanged. **Any stream error falls back to the buffered
  `/chat`** (one retry, then the normal error path) — the UI must never be
  less reliable than before M30.

### 5. CLI (one-shot + REPL)
- When the routed adapter streams, chunks print to stdout as they arrive
  (answer-only contract holds — chunks ARE the answer; status stays on
  stderr; spinner stops at first chunk). Non-streaming: exactly today's
  behavior. `--no-stream` flag forces buffered mode (scripting stability).

## Tests (all mocked — no real SDKs/network)
- Adapter: fake OpenAI stream (chunk objects) → text chunks + final response
  w/ assembled content; mid-stream exception → failure response; usage
  captured when the fake final chunk carries it.
- Router: streaming adapter → chunks then done (order, trace recorded,
  `on_attempt` fired); non-streaming adapter → single chunk + done;
  fallback across a failing provider to a streaming one.
- HTTP: `/chat/stream` SSE framing (chunk events + done payload incl.
  `conversation_id`), history file written on completion, bad
  `conversation_id` → 400; `/chat` regression untouched.
- UI (jsdom): reader loop assembles chunks into one bubble; falls back to
  `/chat` when the stream endpoint errors (fetch mock).
- CLI: scripted stream prints chunks in order; `--no-stream` buffers.

## Version: **3.0.0** (`core/version.py`). CHANGELOG (major-release entry),
INVARIANTS (streaming contracts: adapters bounded, honest degradation, SSE
done-event carries the trace, UI fallback), TESTING, ARCHITECTURE/CLAUDE.md
(map + roadmap: 3.0 shipped), PLATFORMS.md note (streaming is transport-
dependent: API transports stream, CLI transports answer whole).

## Self-review / risks
- Highest-risk piece: the thread→async bridge in the SSE route. Keep it
  boring: iterate the sync generator with repeated `asyncio.to_thread(next,
  it, sentinel)` steps — slower per chunk but simple and loop-safe.
- Do not fork routing logic between `route()`/`route_stream()` — one
  attempt-loop, two delivery modes; a divergence here would be the M26.18
  suffix-bug class of mistake.
- The buffered `/chat` stays byte-compatible — it is the safety net and the
  API contract for anything scripted against 2.x.
- Out of scope: WebSockets, token-level usage ticking in the UI mid-stream,
  streaming for CLI transports, SSE reconnection/resume.
