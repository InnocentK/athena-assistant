/**
 * chat.js — Athena Assistant browser chat UI
 *
 * Vanilla JS, no frameworks. Works in Firefox, Chrome, and Safari.
 * All API calls use fetch(). Message content uses textContent (no XSS).
 *
 * Milestone 3 — conversation history is maintained in memory only.
 * History is cleared on page refresh.
 *
 * Milestone 4 — memory sidebar panel added (review queue and all memories).
 *
 * Milestone 5 — push-to-talk voice integration via voice.js (loaded before
 * this file). Wires the #ptt-btn button to VoiceController and adds TTS
 * playback of assistant responses via SpeechSynthesis.
 *
 * M30 — streaming: sendMessage tries POST /chat/stream (SSE) first and grows
 * the assistant bubble as chunks arrive; any failure before the first chunk
 * falls back to the buffered POST /chat (_sendBuffered), which is unchanged.
 */

/* ---------------------------------------------------------
   State
   --------------------------------------------------------- */
let conversationHistory = []; // [{role, content}, ...]
// M29.1: the persisted conversation id — captured from the first /chat
// response, sent with every later turn so the server appends to one file.
let conversationId = null;
let assistantName = "Athena";
let isThinking = false;

// M26.10: per-panel monotonic load token. Each async panel loader captures the
// current value after clearing its body; if a newer load (e.g. a fast tab
// switch) bumps the token before the fetch resolves, the stale loader bails
// instead of appending its results beneath the newer tab's content.
const _panelLoadToken = { memory: 0, settings: 0, history: 0 };


/* ---------------------------------------------------------
   Voice preferences (M30.6) — per-BROWSER, localStorage-persisted.
   Deliberately NOT in profile.yaml: these are device-level
   accessibility/interaction settings (phone ≠ desktop needs).
   --------------------------------------------------------- */
const _VOICE_PREFS_KEY = "athena-voice-prefs";
const _VOICE_PREF_DEFAULTS = { speak: false, voiceName: "", autoSend: false, continuous: false };
let _voicePrefsMem = null; // fallback when localStorage throws (private mode)

function getVoicePrefs() {
  if (_voicePrefsMem) return Object.assign({}, _VOICE_PREF_DEFAULTS, _voicePrefsMem);
  try {
    const raw = window.localStorage.getItem(_VOICE_PREFS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return Object.assign({}, _VOICE_PREF_DEFAULTS, parsed);
  } catch (_) {
    _voicePrefsMem = {};
    return Object.assign({}, _VOICE_PREF_DEFAULTS);
  }
}

function setVoicePref(key, value) {
  const prefs = getVoicePrefs();
  prefs[key] = value;
  if (_voicePrefsMem) {
    _voicePrefsMem = prefs;
    return;
  }
  try {
    window.localStorage.setItem(_VOICE_PREFS_KEY, JSON.stringify(prefs));
  } catch (_) {
    _voicePrefsMem = prefs;
  }
}


/* ---------------------------------------------------------
   DOM references (populated after DOMContentLoaded)
   --------------------------------------------------------- */
let messagesEl;
let chatWindow;
let messageInput;
let sendBtn;
let statusDot;
let providerBadge;


/* ---------------------------------------------------------
   Initialisation
   --------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
  messagesEl   = document.getElementById("messages");
  chatWindow   = document.getElementById("chat-window");
  messageInput = document.getElementById("message-input");
  sendBtn      = document.getElementById("send-btn");
  statusDot    = document.getElementById("status-dot");
  providerBadge = document.getElementById("provider-badge");

  // Voice setup. Guarded with `typeof` so a failed/absent voice.js can't throw
  // a ReferenceError and abort the whole init handler (M26.10).
  if (typeof voice !== "undefined" && voice.isSupported) {
    var pttBtn = document.getElementById('ptt-btn');
    pttBtn.disabled = false;
    pttBtn.title = 'Click to start voice input';

    voice.onTranscript = function(text) {
      messageInput.value = text;
      autoResizeTextarea();
      // M30.6: auto-send is opt-in — by default the transcript lands in the
      // input for review, exactly like typed text.
      if (getVoicePrefs().autoSend) {
        sendMessage();
      } else {
        messageInput.focus();
      }
    };

    voice.onError = function(msg) {
      appendMessage('error', msg, null, null);
      setStatusDot('error');
    };

    voice.onListeningStart = function() {
      pttBtn.classList.add('listening');
      pttBtn.title = 'Listening... click to stop';
      setStatusDot('thinking');
    };

    voice.onListeningStop = function() {
      pttBtn.classList.remove('listening');
      pttBtn.title = 'Click to start voice input';
      setStatusDot('ready');
    };

    pttBtn.addEventListener('click', function() {
      if (voice.isListening) {
        voice.stopListening();
      } else {
        // M30.6: continuous mode keeps listening across pauses until the
        // button is clicked again; default stays stop-on-pause.
        voice.continuous = getVoicePrefs().continuous;
        voice.startListening();
      }
    });
  } else {
    // Browser doesn't support Web Speech API — leave button disabled with tooltip
    var pttBtn = document.getElementById('ptt-btn');
    pttBtn.title = 'Voice input not supported in this browser. Try Chrome or Edge.';
  }

  // Wire events
  sendBtn.addEventListener("click", sendMessage);

  // M29.3: file attach — upload to data/uploads/ and reference it in the input.
  const attachBtn = document.getElementById("attach-btn");
  const attachInput = document.getElementById("attach-input");
  if (attachBtn && attachInput) {
    attachBtn.addEventListener("click", function () {
      attachInput.click();
    });
    attachInput.addEventListener("change", async function () {
      const file = attachInput.files && attachInput.files[0];
      attachInput.value = ""; // allow re-picking the same file
      if (!file) return;
      attachBtn.disabled = true;
      try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch("/files/upload", { method: "POST", body: form });
        if (!res.ok) {
          const err = await res.json().catch(function () { return {}; });
          appendMessage("error", "Upload failed: " + (err.detail || res.status), null, null);
          return;
        }
        const data = await res.json();
        const ref = "[Attached file: " + data.path + "]\n";
        messageInput.value = ref + messageInput.value;
        messageInput.focus();
      } catch (_) {
        appendMessage("error", "Upload failed: network error", null, null);
      } finally {
        attachBtn.disabled = false;
      }
    });
  }
  messageInput.addEventListener("keydown", handleInputKeydown);
  messageInput.addEventListener("input", autoResizeTextarea);

  // Wire memory panel events
  document.getElementById("memory-btn").addEventListener("click", openMemoryPanel);
  document.getElementById("memory-close-btn").addEventListener("click", closeMemoryPanel);
  document.querySelectorAll(".mem-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      switchMemoryTab(btn.dataset.tab);
    });
  });

  // Wire settings panel events (Milestone 19)
  document.getElementById("settings-btn").addEventListener("click", openSettingsPanel);
  document.getElementById("settings-close-btn").addEventListener("click", closeSettingsPanel);
  document.querySelectorAll(".set-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      switchSettingsTab(btn.dataset.tab);
    });
  });

  // Wire history & attachments panel events (Milestone 20)
  document.getElementById("history-btn").addEventListener("click", openHistoryPanel);
  document.getElementById("history-close-btn").addEventListener("click", closeHistoryPanel);
  document.querySelectorAll(".hist-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      switchHistoryTab(btn.dataset.tab);
    });
  });

  // Load profile and providers, then show welcome
  loadProfile()
    .then(function () { return loadProviders(); })
    .then(function () {
      appendMessage(
        "assistant",
        "Hello. I'm " + assistantName + ". How can I help?",
        null,
        null,
        /* isWelcome */ true
      );
      messageInput.focus();
    });
});


/* ---------------------------------------------------------
   Profile & provider loading
   --------------------------------------------------------- */
// Startup provider chip reflects this (M26.1); null → neutral/blank.
let _preferredProvider = null;

async function loadProfile() {
  try {
    const res = await fetch("/profile");
    if (!res.ok) return; // fallback stays "Athena"
    const data = await res.json();
    if (data && data.name) {
      assistantName = data.name;
    }
    if (data && data.routing) {
      _preferredProvider = data.routing.preferred_provider || null;
    }
  } catch (_) {
    // Network failure — keep default name
  }
}

async function loadProviders() {
  // Startup chip (M26.1): show the configured preferred provider if set;
  // otherwise stay neutral/blank until a request actually selects a provider.
  // (Previously this showed the first available provider, which was misleading.)
  updateProviderBadge(_preferredProvider || null);
}


/* ---------------------------------------------------------
   Send message (M30: streaming-first, buffered fallback)
   --------------------------------------------------------- */
async function sendMessage() {
  if (isThinking) return;

  const text = messageInput.value.trim();
  if (!text) return;

  // Enter thinking state
  isThinking = true;
  setInputEnabled(false);
  setStatusDot("thinking");
  setChatStatus("Working…");
  clearTextarea();

  // Show user message immediately
  appendMessage("user", text, null, null);

  // Build history slice to send (all turns BEFORE this new user message)
  // The backend appends `message` as the final user turn itself.
  const historyToSend = conversationHistory.slice(); // copy before pushing

  // Record user turn in local history
  conversationHistory.push({ role: "user", content: text });

  try {
    // M30: try the streaming endpoint first. It returns false ONLY when
    // nothing has been rendered yet (endpoint missing/erroring, network
    // failure before the first chunk) — then the buffered /chat is the
    // safety net, so the UI is never less reliable than before M30.
    const handled = await _sendStreaming(text, historyToSend);
    if (!handled) {
      await _sendBuffered(text, historyToSend);
    }
  } finally {
    // Re-enable input regardless of outcome
    isThinking = false;
    setInputEnabled(true);
    setChatStatus("");
    messageInput.focus();
  }
}


/**
 * M30 — POST /chat/stream and render the reply incrementally.
 *
 * Returns true when this attempt handled the turn (answer or error rendered);
 * returns false ONLY when it is safe to fall back to the buffered /chat:
 * nothing rendered yet and the request failed (non-OK status, no streaming
 * body, network error, or stream ended before any chunk/done).
 */
async function _sendStreaming(text, historyToSend) {
  let res;
  try {
    res = await fetch("/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history: historyToSend,
        conversation_id: conversationId, // M29.1 (null → server creates one)
      }),
    });
  } catch (_) {
    return false; // network error before anything rendered — fall back
  }
  if (!res.ok || !res.body || typeof res.body.getReader !== "function") {
    return false; // older server / HTTP error / no ReadableStream — fall back
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let stream = null; // {wrapper, bubble} — created on the first chunk
  let assembled = "";
  let data = null; // the `done` event's payload (mirrors ChatResponse)

  try {
    for (;;) {
      const step = await reader.read();
      if (step.done) break;
      buffer += decoder.decode(step.value, { stream: true });
      const parsed = _parseSSEFrames(buffer);
      buffer = parsed.rest;
      for (let i = 0; i < parsed.frames.length; i++) {
        const frame = parsed.frames[i];
        let payload;
        try {
          payload = JSON.parse(frame.data);
        } catch (_) {
          continue; // skip a malformed frame; the done frame decides the turn
        }
        if (frame.event === "chunk") {
          const t = typeof payload.text === "string" ? payload.text : "";
          if (t) {
            if (!stream) stream = _beginStreamingBubble();
            assembled += t;
            stream.bubble.textContent = assembled; // textContent — no XSS
            scrollToBottom();
          }
        } else if (frame.event === "done") {
          data = payload;
        }
      }
      if (data) break;
    }
  } catch (_) {
    if (!stream) return false; // nothing rendered — buffered fallback
    appendMessage("error", "The stream was interrupted.", null, null);
    setStatusDot("error");
    return true; // partial text already visible: do NOT re-send via /chat
  }

  if (!data) {
    if (!stream) return false; // no chunks, no done — safe to fall back
    appendMessage("error", "The stream ended unexpectedly.", null, null);
    setStatusDot("error");
    return true;
  }

  // --- Render phase: mirrors _sendBuffered exactly ---
  if (data.conversation_id) {
    conversationId = data.conversation_id; // M29.1: adopt the server's id
  }

  if (data.success === false) {
    // Failure — error bubble, and never push to conversationHistory (M26.10:
    // failure text must not be replayed as context on later turns).
    const reason = data.error || data.response || "The request failed.";
    appendMessage("error", reason, data.provider, data.model);
    setStatusDot("error");
    appendDiagnostics(data.diagnostics);
    return true;
  }

  // data.response is the authoritative full text (chunks are progressive
  // display); reconcile in the unlikely case they diverge.
  const fullText =
    typeof data.response === "string" && data.response ? data.response : assembled;
  if (!stream) {
    // Success with no chunk frames (defensive) — render buffered-style.
    appendMessage("assistant", fullText, data.provider, data.model);
  } else {
    if (fullText !== assembled) stream.bubble.textContent = fullText;
    _finishStreamingBubble(stream, data.provider, data.model);
  }
  conversationHistory.push({ role: "assistant", content: fullText });
  setStatusDot("ready");
  if (data.provider) {
    updateProviderBadge(data.provider);
  }
  // M30.6: reading answers aloud is opt-in (default off), with the chosen voice.
  const vpStream = getVoicePrefs();
  if (vpStream.speak && typeof voice !== "undefined" && voice.isTTSSupported) {
    try {
      voice.speak(fullText, vpStream.voiceName);
    } catch (_) {}
  }
  appendDiagnostics(data.diagnostics);
  return true;
}


/**
 * Buffered POST /chat — the pre-M30 path, byte-identical behavior. Used as
 * the fallback whenever streaming could not start.
 */
async function _sendBuffered(text, historyToSend) {
  // --- Network phase: this try/catch guards ONLY the fetch + JSON parse.
  // A rendering/TTS error later must NOT be reported as a network error (M26.10).
  let res;
  try {
    res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        history: historyToSend,
        conversation_id: conversationId, // M29.1 (null → server creates one)
      }),
    });
  } catch (_) {
    appendMessage("error", "Network error — could not reach the assistant.", null, null);
    setStatusDot("error");
    return; // sendMessage's finally still resets input state
  }

  if (!res.ok) {
    // HTTP error (4xx / 5xx)
    let detail = "Request failed (" + res.status + ").";
    try {
      const errBody = await res.json();
      if (errBody && errBody.detail) detail = errBody.detail;
    } catch (_) {}
    appendMessage("error", detail, null, null);
    setStatusDot("error");
    return;
  }

  let data;
  try {
    data = await res.json();
  } catch (_) {
    appendMessage("error", "Received a malformed response from the assistant.", null, null);
    setStatusDot("error");
    return;
  }

  // --- Render phase (network already succeeded). ---
  // M29.1: adopt the server's conversation id (first turn creates it).
  if (data.conversation_id) {
    conversationId = data.conversation_id;
  }
  if (data.success === false) {
    // Provider returned a failure response — show as error style, but do NOT
    // record it as an assistant turn (M26.10): otherwise "All providers
    // failed." would be replayed to providers on every later message.
    appendMessage("error", data.response, data.provider, data.model);
    setStatusDot("error");
  } else {
    conversationHistory.push({ role: "assistant", content: data.response });
    appendMessage("assistant", data.response, data.provider, data.model);
    setStatusDot("ready");
    if (data.provider) {
      updateProviderBadge(data.provider);
    }
    // Speak the response if enabled (M30.6: opt-in, default off). Guarded so
    // a missing voice.js (or a speak() error) can't break the rendered answer.
    const vpBuf = getVoicePrefs();
    if (vpBuf.speak && typeof voice !== "undefined" && voice.isTTSSupported) {
      try {
        voice.speak(data.response, vpBuf.voiceName);
      } catch (_) {}
    }
  }

  // M24/M24.5: diagnostics under the answer (summary + timeline + details)
  appendDiagnostics(data.diagnostics);
}


/* ---------------------------------------------------------
   SSE helpers (M30)
   --------------------------------------------------------- */
/**
 * Parse complete SSE frames out of `buffer` (frames end with a blank line).
 * Returns {frames: [{event, data}], rest} where rest is the unfinished tail
 * to carry into the next read. Multi-`data:`-line frames are joined with \n
 * per the SSE spec (the server emits single-line JSON, but be liberal).
 */
function _parseSSEFrames(buffer) {
  const frames = [];
  let idx;
  while ((idx = buffer.indexOf("\n\n")) !== -1) {
    const raw = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    let event = "message";
    const dataLines = [];
    raw.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) {
        event = line.slice(6).trim();
      } else if (line.indexOf("data:") === 0) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    });
    if (dataLines.length) {
      frames.push({ event: event, data: dataLines.join("\n") });
    }
  }
  return { frames: frames, rest: buffer };
}

/**
 * Create the growing assistant bubble for a streaming reply: the wrapper and
 * bubble match appendMessage's DOM exactly, but the meta line is deferred to
 * _finishStreamingBubble (provider/model are only known at `done`).
 */
function _beginStreamingBubble() {
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper message-assistant";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = "";
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  scrollToBottom();
  return { wrapper: wrapper, bubble: bubble };
}

/** Attach the meta line (provider/model + timestamp) once the reply is done. */
function _finishStreamingBubble(stream, provider, model) {
  const meta = document.createElement("div");
  meta.className = "meta";
  if (provider) {
    const providerSpan = document.createElement("span");
    providerSpan.className = "provider-label";
    providerSpan.textContent = provider + (model ? " / " + model : "");
    meta.appendChild(providerSpan);
  }
  const timeSpan = document.createElement("span");
  timeSpan.className = "timestamp";
  timeSpan.textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  meta.appendChild(timeSpan);
  stream.wrapper.appendChild(meta);
}


/* ---------------------------------------------------------
   Status / progress (Milestone 24) + diagnostics view (M24.5)
   All rendered from ChatResponse.diagnostics — the content-free
   M22 trace. No backend/transport changes; reconstructed at
   completion (no streaming/polling).
   --------------------------------------------------------- */
function setChatStatus(text) {
  // Toggles the in-flight indicator. The indeterminate progress bar lives
  // inside #chat-status and animates via CSS while the element is visible;
  // we only touch the text span so the bar markup is preserved.
  const el = document.getElementById("chat-status");
  if (!el) return;
  const textEl = el.querySelector(".chat-status-text");
  if (text) {
    if (textEl) textEl.textContent = text;
    el.classList.remove("hidden");
  } else {
    el.classList.add("hidden");
  }
}

/**
 * Render the diagnostics block under an answer: a concise summary line, a
 * compact proportional provider timeline, and a collapsed details disclosure.
 * Quiet by default — supporting UI, not the dominant element.
 */
function appendDiagnostics(diag) {
  const summary = buildDiagnosticsSummary(diag);
  if (!summary && !diag) return;

  const box = document.createElement("div");
  box.className = "message-diagnostics";

  if (summary) {
    const s = document.createElement("div");
    s.className = "message-summary";
    s.textContent = summary; // textContent — no XSS
    box.appendChild(s);
  }
  const usageText = buildUsageText(diag); // M27.1
  if (usageText) {
    const u = document.createElement("div");
    u.className = "message-usage";
    u.textContent = usageText; // textContent — counts only, no XSS
    box.appendChild(u);
  }
  const timeline = buildTimeline(diag);
  if (timeline) box.appendChild(timeline);
  const details = buildDetails(diag);
  if (details) box.appendChild(details);

  if (box.childNodes.length) {
    messagesEl.appendChild(box);
    scrollToBottom();
  }
}

function diagOutcomeClass(outcome) {
  if (outcome === "ok") return "ok";
  if (outcome === "skipped" || outcome === "unavailable") return "skip";
  return "fail"; // failure | exception | anything unexpected
}

function diagMs(v) {
  return typeof v === "number" && v > 0 ? Math.round(v) + "ms" : "—";
}

/**
 * Compact, proportional, outcome-coloured timeline — one segment per attempt,
 * width ~ duration_ms / total. Labels truncate; full info is in the title
 * tooltip so narrow segments stay readable without visual noise.
 */
function buildTimeline(diag) {
  if (!diag || !Array.isArray(diag.records) || !diag.records.length) return null;

  const total =
    typeof diag.total_ms === "number" && diag.total_ms > 0 ? diag.total_ms : 0;
  const sumDur = diag.records.reduce(function (a, r) {
    return a + (typeof r.duration_ms === "number" ? r.duration_ms : 0);
  }, 0);
  const denom = total || sumDur || 1;

  const row = document.createElement("div");
  row.className = "diag-timeline";
  row.setAttribute("role", "img");
  row.setAttribute("aria-label", "Provider attempt timeline");

  diag.records.forEach(function (r) {
    const outcome = r.outcome || "ok";
    const seg = document.createElement("span");
    seg.className = "diag-seg diag-seg--" + diagOutcomeClass(outcome);
    if (diag.selected && r.provider === diag.selected) {
      seg.classList.add("diag-seg--selected");
    }
    const dur = typeof r.duration_ms === "number" ? r.duration_ms : 0;
    seg.style.flexGrow = String(Math.max(1, Math.round((dur / denom) * 100)));

    const label = (r.provider || "?") + (r.transport ? "/" + r.transport : "");
    seg.title = label + " — " + outcome + (dur ? " · " + (dur / 1000).toFixed(1) + "s" : "");

    const lab = document.createElement("span");
    lab.className = "diag-seg-label";
    lab.textContent = label; // truncates via CSS; full text in title
    seg.appendChild(lab);
    row.appendChild(seg);
  });
  return row;
}

/**
 * Collapsed "Details" disclosure over the full RequestTrace: request meta plus
 * a per-attempt table (timings + outcome + short error_kind — no message content).
 */
function buildDetails(diag) {
  if (!diag) return null;
  const records = Array.isArray(diag.records) ? diag.records : [];

  const det = document.createElement("details");
  det.className = "diag-details";
  const sum = document.createElement("summary");
  sum.textContent = "Details";
  det.appendChild(sum);

  const bits = [];
  if (diag.mode) bits.push("mode " + diag.mode);
  if (typeof diag.total_ms === "number") bits.push("total " + (diag.total_ms / 1000).toFixed(1) + "s");
  if (Array.isArray(diag.attempt_order) && diag.attempt_order.length) {
    bits.push("order " + diag.attempt_order.join(" → "));
  }
  if (diag.request_id) bits.push("id " + diag.request_id);
  if (bits.length) {
    const meta = document.createElement("div");
    meta.className = "diag-meta";
    meta.textContent = bits.join("  ·  ");
    det.appendChild(meta);
  }

  if (records.length) {
    const table = document.createElement("table");
    table.className = "diag-table";
    const head = document.createElement("tr");
    ["provider", "transport", "outcome", "avail", "call", "total", "note"].forEach(function (h) {
      const th = document.createElement("th");
      th.textContent = h;
      head.appendChild(th);
    });
    table.appendChild(head);
    records.forEach(function (r) {
      const tr = document.createElement("tr");
      const selected = diag.selected && r.provider === diag.selected;
      const cells = [
        (r.provider || "") + (selected ? " ✓" : ""),
        r.transport || "",
        r.outcome || "",
        diagMs(r.availability_ms),
        diagMs(r.call_ms),
        diagMs(r.duration_ms),
        r.error_kind || r.error || "",
      ];
      cells.forEach(function (c) {
        const td = document.createElement("td");
        td.textContent = c; // textContent — no XSS
        tr.appendChild(td);
      });
      table.appendChild(tr);
    });
    det.appendChild(table);
  }
  return det;
}

/**
 * Build a concise, low-noise one-line summary from the M22 diagnostics trace.
 * Examples:
 *   "Answered via grok/api in 0.8s."
 *   "claude/cli unavailable; answered via grok/api in 0.8s."
 *   "No provider answered."
 */
function buildDiagnosticsSummary(diag) {
  if (!diag || !Array.isArray(diag.records)) return "";
  function label(r) {
    return r.provider + (r.transport ? "/" + r.transport : "");
  }
  const sel = diag.selected;
  if (!sel) return "No provider answered.";
  const totalS =
    typeof diag.total_ms === "number" ? (diag.total_ms / 1000).toFixed(1) + "s" : "";
  const selRec = diag.records.find(function (r) { return r.provider === sel; });
  const selLabel = selRec ? label(selRec) : sel;
  const priors = diag.records
    .filter(function (r) { return r.provider !== sel && r.outcome !== "ok"; })
    .map(function (r) { return label(r) + " " + r.outcome; });
  const core = "answered via " + selLabel + (totalS ? " in " + totalS : "") + ".";
  if (priors.length) {
    return priors.join("; ") + "; " + core;
  }
  return core.charAt(0).toUpperCase() + core.slice(1);
}


/**
 * Token-usage line for the selected provider (M27.1), from the M22 trace.
 * Content-free — counts only. Examples:
 *   "Tokens: 1,204 prompt + 320 completion = 1,524 total"
 *   "Tokens: unavailable"   (CLI transports / providers that don't report)
 * "" when there is no usable trace.
 */
function buildUsageText(diag) {
  if (!diag || !Array.isArray(diag.records) || !diag.selected) return "";
  const selRec = diag.records.find(function (r) {
    return r.provider === diag.selected;
  });
  const usage = selRec && selRec.usage;
  if (!usage || typeof usage !== "object") return "Tokens: unavailable";
  function fmt(n) {
    return typeof n === "number" ? n.toLocaleString() : null;
  }
  const parts = [];
  if (typeof usage.prompt_tokens === "number") {
    parts.push(fmt(usage.prompt_tokens) + " prompt");
  }
  if (typeof usage.completion_tokens === "number") {
    parts.push(fmt(usage.completion_tokens) + " completion");
  }
  let body = parts.join(" + ");
  if (typeof usage.total_tokens === "number") {
    body = (body ? body + " = " : "") + fmt(usage.total_tokens) + " total";
  }
  return body ? "Tokens: " + body : "Tokens: unavailable";
}


/* ---------------------------------------------------------
   Append a message bubble to the chat window
   --------------------------------------------------------- */
/**
 * @param {'user'|'assistant'|'error'} role
 * @param {string} content
 * @param {string|null} provider  — shown in .meta for assistant messages
 * @param {string|null} model     — shown in .meta alongside provider
 * @param {boolean} [isWelcome]   — omit timestamp and provider label
 */
function appendMessage(role, content, provider, model, isWelcome) {
  // Wrapper div
  const wrapper = document.createElement("div");
  wrapper.className = "message-wrapper message-" + role;

  // Bubble
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "error") {
    bubble.classList.add("bubble-error");
  }
  bubble.textContent = content; // textContent — no XSS
  wrapper.appendChild(bubble);

  // Meta line (assistant and error messages only, skip for welcome)
  if (!isWelcome && (role === "assistant" || role === "error")) {
    const meta = document.createElement("div");
    meta.className = "meta";

    if (provider) {
      const providerSpan = document.createElement("span");
      providerSpan.className = "provider-label";
      providerSpan.textContent = provider + (model ? " / " + model : "");
      meta.appendChild(providerSpan);
    }

    const timeSpan = document.createElement("span");
    timeSpan.className = "timestamp";
    timeSpan.textContent = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
    meta.appendChild(timeSpan);

    wrapper.appendChild(meta);
  }

  // User messages: add just a timestamp
  if (!isWelcome && role === "user") {
    const meta = document.createElement("div");
    meta.className = "meta";
    const timeSpan = document.createElement("span");
    timeSpan.className = "timestamp";
    timeSpan.textContent = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
    meta.appendChild(timeSpan);
    wrapper.appendChild(meta);
  }

  messagesEl.appendChild(wrapper);
  scrollToBottom();
}


/* ---------------------------------------------------------
   Scroll chat window to bottom
   --------------------------------------------------------- */
function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}


/* ---------------------------------------------------------
   Provider badge
   --------------------------------------------------------- */
function updateProviderBadge(providerName) {
  if (providerName) {
    providerBadge.textContent = providerName;
    providerBadge.classList.remove("no-provider");
    providerBadge.classList.remove("hidden");
  } else {
    // Neutral: blank/hidden until a request actually selects a provider (M26.1).
    providerBadge.textContent = "";
    providerBadge.classList.remove("no-provider");
    providerBadge.classList.add("hidden");
  }
}


/* ---------------------------------------------------------
   Status dot
   --------------------------------------------------------- */
function setStatusDot(state) {
  // state: 'ready' | 'thinking' | 'error'
  statusDot.className = "status-" + state;
}


/* ---------------------------------------------------------
   Input helpers
   --------------------------------------------------------- */
function setInputEnabled(enabled) {
  messageInput.disabled = !enabled;
  sendBtn.disabled = !enabled;
}

function clearTextarea() {
  messageInput.value = "";
  messageInput.style.height = "auto";
}

function handleInputKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResizeTextarea() {
  // Reset to auto so shrinking works, then grow to fit content
  messageInput.style.height = "auto";
  const maxHeight = 120; // px — matches CSS max-height
  messageInput.style.height = Math.min(messageInput.scrollHeight, maxHeight) + "px";
}


/* ---------------------------------------------------------
   Memory sidebar — state
   --------------------------------------------------------- */
let _activeMemoryTab = "pending";


/* ---------------------------------------------------------
   Memory sidebar — open / close / switch
   --------------------------------------------------------- */
function openMemoryPanel() {
  document.getElementById("settings-panel").classList.add("hidden"); // one panel at a time
  document.getElementById("history-panel").classList.add("hidden");
  document.getElementById("memory-panel").classList.remove("hidden");
  loadMemoryTab(_activeMemoryTab);
}

function closeMemoryPanel() {
  document.getElementById("memory-panel").classList.add("hidden");
}

function switchMemoryTab(tab) {
  _activeMemoryTab = tab;
  document.querySelectorAll(".mem-tab").forEach(function (btn) {
    if (btn.dataset.tab === tab) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });
  loadMemoryTab(tab);
}

function loadMemoryTab(tab) {
  if (tab === "pending") {
    loadPendingMemories();
  } else {
    loadAllMemories();
  }
}


/* ---------------------------------------------------------
   Memory sidebar — data loading
   --------------------------------------------------------- */
async function loadPendingMemories() {
  const body = document.getElementById("memory-panel-body");
  const token = ++_panelLoadToken.memory;
  body.textContent = "";

  try {
    const res = await fetch("/memory/pending");
    if (token !== _panelLoadToken.memory) return; // superseded by a newer load
    if (!res.ok) {
      const errNode = document.createTextNode("Failed to load pending memories.");
      body.appendChild(errNode);
      return;
    }
    const entries = await res.json();
    if (token !== _panelLoadToken.memory) return;

    if (!Array.isArray(entries) || entries.length === 0) {
      const empty = document.createElement("p");
      empty.className = "memory-empty";
      empty.textContent = "No entries.";
      body.appendChild(empty);
      return;
    }

    entries.forEach(function (entry) {
      const card = renderMemoryEntry(entry, [
        {
          label: "Approve",
          className: "mem-btn-approve",
          onClick: function () { approveMemory(entry.id); },
        },
        {
          label: "Discard",
          className: "mem-btn-discard",
          onClick: function () { discardMemory(entry.id); },
        },
      ]);
      body.appendChild(card);
    });
  } catch (_) {
    const errNode = document.createTextNode("Network error loading pending memories.");
    body.appendChild(errNode);
  }
}

async function loadAllMemories() {
  const body = document.getElementById("memory-panel-body");
  const token = ++_panelLoadToken.memory;
  body.textContent = "";

  try {
    const res = await fetch("/memory");
    if (token !== _panelLoadToken.memory) return; // superseded by a newer load
    if (!res.ok) {
      const errNode = document.createTextNode("Failed to load memories.");
      body.appendChild(errNode);
      return;
    }
    const data = await res.json();
    if (token !== _panelLoadToken.memory) return;

    const categories = Object.keys(data);
    let totalEntries = 0;

    categories.forEach(function (category) {
      const entries = data[category];
      if (!Array.isArray(entries) || entries.length === 0) return;

      totalEntries += entries.length;

      const heading = document.createElement("p");
      heading.className = "memory-category-heading";
      heading.textContent = category;
      body.appendChild(heading);

      entries.forEach(function (entry) {
        const card = renderMemoryEntry(entry, [
          {
            label: "Delete",
            className: "mem-btn-delete",
            onClick: function () { deleteMemory(entry.id); },
          },
        ]);
        body.appendChild(card);
      });
    });

    if (totalEntries === 0) {
      const empty = document.createElement("p");
      empty.className = "memory-empty";
      empty.textContent = "No entries.";
      body.appendChild(empty);
    }
  } catch (_) {
    const errNode = document.createTextNode("Network error loading memories.");
    body.appendChild(errNode);
  }
}


/* ---------------------------------------------------------
   Memory sidebar — render helpers
   --------------------------------------------------------- */
/**
 * Render a single memory entry card.
 *
 * @param {Object} entry    — the memory entry dict from the API
 * @param {Array}  actions  — array of {label, className, onClick} button descriptors
 * @returns {HTMLElement}   — a .memory-entry div
 */
function renderMemoryEntry(entry, actions) {
  const card = document.createElement("div");
  card.className = "memory-entry";

  // Key line
  const keyEl = document.createElement("div");
  keyEl.className = "memory-entry-key";
  keyEl.textContent = entry.key || "(no key)";
  card.appendChild(keyEl);

  // Value line
  const valEl = document.createElement("div");
  valEl.className = "memory-entry-value";
  valEl.textContent = entry.value || "";
  card.appendChild(valEl);

  // Meta line — show reason (pending) or category + source (saved)
  const metaEl = document.createElement("div");
  metaEl.className = "memory-entry-meta";
  let metaParts = [];
  if (entry.reason) {
    metaParts.push(entry.reason);
  }
  if (entry.category) {
    metaParts.push(entry.category);
  }
  if (entry.source) {
    metaParts.push(entry.source);
  }
  if (entry.created_at) {
    metaParts.push(entry.created_at);
  }
  metaEl.textContent = metaParts.join(" · ");
  card.appendChild(metaEl);

  // Action buttons
  if (actions && actions.length > 0) {
    const actionsEl = document.createElement("div");
    actionsEl.className = "memory-entry-actions";

    actions.forEach(function (action) {
      const btn = document.createElement("button");
      btn.className = "mem-btn " + action.className;
      btn.textContent = action.label;
      btn.addEventListener("click", action.onClick);
      actionsEl.appendChild(btn);
    });

    card.appendChild(actionsEl);
  }

  return card;
}


/* ---------------------------------------------------------
   Memory sidebar — actions
   --------------------------------------------------------- */
async function approveMemory(id) {
  try {
    await fetch("/memory/pending/" + id + "/approve", { method: "POST" });
  } catch (_) {
    // Silently ignore network errors — panel reload will show current state
  }
  loadPendingMemories();
}

async function discardMemory(id) {
  try {
    await fetch("/memory/pending/" + id, { method: "DELETE" });
  } catch (_) {
    // Silently ignore network errors
  }
  loadPendingMemories();
}

async function deleteMemory(id) {
  try {
    await fetch("/memory/" + id, { method: "DELETE" });
  } catch (_) {
    // Silently ignore network errors
  }
  loadAllMemories();
}


/* ---------------------------------------------------------
   Settings panel — open / close / switch (Milestone 19)
   Read-only view; mirrors the memory panel pattern. One panel
   is open at a time. All data comes from existing GET endpoints.
   --------------------------------------------------------- */
let _activeSettingsTab = "profile";

function openSettingsPanel() {
  document.getElementById("memory-panel").classList.add("hidden"); // one panel at a time
  document.getElementById("history-panel").classList.add("hidden");
  document.getElementById("settings-panel").classList.remove("hidden");
  loadSettingsTab(_activeSettingsTab);
}

function closeSettingsPanel() {
  document.getElementById("settings-panel").classList.add("hidden");
}

function switchSettingsTab(tab) {
  _activeSettingsTab = tab;
  document.querySelectorAll(".set-tab").forEach(function (btn) {
    if (btn.dataset.tab === tab) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });
  loadSettingsTab(tab);
}

function loadSettingsTab(tab) {
  if (tab === "providers") {
    loadSettingsProviders();
  } else if (tab === "integrations") {
    loadSettingsIntegrations();
  } else {
    loadSettingsProfile();
  }
}


/* ---------------------------------------------------------
   Settings panel — render helpers (XSS-safe DOM only)
   --------------------------------------------------------- */
function _settingsSectionTitle(text) {
  const el = document.createElement("div");
  el.className = "settings-section-title";
  el.textContent = text;
  return el;
}

function _settingsRow(key, value, valClass) {
  const row = document.createElement("div");
  row.className = "settings-row";

  const k = document.createElement("span");
  k.className = "settings-key";
  k.textContent = key;

  const v = document.createElement("span");
  v.className = "settings-val" + (valClass ? " " + valClass : "");
  if (value === true) {
    v.textContent = "yes";
  } else if (value === false) {
    v.textContent = "no";
  } else if (value === null || value === undefined || value === "") {
    v.textContent = "—";
  } else {
    v.textContent = String(value);
  }

  row.appendChild(k);
  row.appendChild(v);
  return row;
}

function _settingsMessage(body, text, cls) {
  const el = document.createElement("div");
  el.className = cls || "settings-empty";
  el.textContent = text;
  body.appendChild(el);
}


/* ---------------------------------------------------------
   Settings panel — data loading (read-only; existing GET endpoints)
   --------------------------------------------------------- */
// M26: the three editable routing modes (mirrors the server's accepted set).
const EDITABLE_MODES = ["quality-first", "balanced", "budget-first"];

async function loadSettingsProfile() {
  const body = document.getElementById("settings-panel-body");
  const token = ++_panelLoadToken.settings;
  body.textContent = "";
  try {
    const [profileRes, healthRes, providersRes, profilesRes] = await Promise.all([
      fetch("/profile"),
      fetch("/health"),
      fetch("/providers"),
      fetch("/profiles"),
    ]);
    if (token !== _panelLoadToken.settings) return; // superseded by a newer load
    if (!profileRes.ok) {
      _settingsMessage(body, "Failed to load profile.", "settings-error");
      return;
    }
    const p = await profileRes.json();
    const health = healthRes.ok ? await healthRes.json() : {};
    const providers = providersRes.ok ? await providersRes.json() : [];
    if (token !== _panelLoadToken.settings) return;
    const routing = p.routing || {};
    const memory = p.memory || {};

    body.appendChild(_settingsSectionTitle("Profile"));
    body.appendChild(_settingsRow("Name", p.name));
    // App (release) version vs profile schema version are distinct (M26.2).
    body.appendChild(_settingsRow("App version", health.version));
    body.appendChild(_settingsRow("Profile schema version", p.version));

    // --- Active profile switcher (M28.5) ---
    const profiles = profilesRes && profilesRes.ok ? await profilesRes.json() : [];
    if (token !== _panelLoadToken.settings) return;
    if (Array.isArray(profiles) && profiles.length > 1) {
      body.appendChild(_settingsSectionTitle("Active profile"));
      let activeName = "";
      const profileOptions = profiles.map(function (pr) {
        if (pr.active) activeName = pr.name;
        return { value: pr.name, label: pr.display_name + " (" + pr.name + ")" };
      });
      const profileSelect = _settingsSelect(profileOptions, activeName);
      body.appendChild(_settingsControlRow("Profile", profileSelect));
      const activateBtn = document.createElement("button");
      activateBtn.className = "settings-save-btn";
      activateBtn.textContent = "Activate";
      activateBtn.addEventListener("click", async function () {
        if (profileSelect.value === activeName) return;
        activateBtn.disabled = true;
        try {
          const res = await fetch("/profiles/activate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: profileSelect.value }),
          });
          if (res.ok) {
            // Full reload: name, memory, saved items all change with the profile.
            window.location.reload();
          } else {
            const err = await res.json().catch(function () { return {}; });
            _settingsMessage(body, "Switch failed: " + (err.detail || res.status), "settings-error");
            activateBtn.disabled = false;
          }
        } catch (e) {
          _settingsMessage(body, "Switch failed: network error", "settings-error");
          activateBtn.disabled = false;
        }
      });
      body.appendChild(activateBtn);
    }

    // --- Editable settings (M26): system prompt, mode, preferred provider ---
    body.appendChild(_settingsSectionTitle("System prompt"));
    const promptInput = document.createElement("textarea");
    promptInput.className = "settings-edit-textarea";
    promptInput.rows = 5;
    promptInput.value = p.system_prompt || "";
    body.appendChild(promptInput);

    body.appendChild(_settingsSectionTitle("Routing"));
    // M26.10: guarantee the canonical value is always a selectable option so the
    // <select> can't silently fall back to its first option and have a save wipe
    // a field the user didn't touch (e.g. when /providers failed to load, or the
    // stored mode is legacy). The option VALUE is the real canonical value.
    const canonMode = routing.mode || "";
    const modeOptions = EDITABLE_MODES.map(function (m) { return { value: m, label: m }; });
    if (canonMode && !modeOptions.some(function (o) { return o.value === canonMode; })) {
      modeOptions.push({ value: canonMode, label: canonMode + " (current)" });
    }
    const modeSelect = _settingsSelect(modeOptions, canonMode);
    body.appendChild(_settingsControlRow("Mode", modeSelect));

    const canonProv = routing.preferred_provider || "";
    const provOptions = [{ value: "", label: "Follow mode (none)" }].concat(
      providers.map(function (pr) { return { value: pr.name, label: pr.name }; })
    );
    if (canonProv && !provOptions.some(function (o) { return o.value === canonProv; })) {
      provOptions.push({ value: canonProv, label: canonProv + " (current)" });
    }
    const provSelect = _settingsSelect(provOptions, canonProv);
    body.appendChild(_settingsControlRow("Preferred provider", provSelect));
    if (!Array.isArray(providers) || providers.length === 0) {
      const provNote = document.createElement("div");
      provNote.className = "settings-note";
      provNote.textContent = "Provider list unavailable — showing the configured value only.";
      body.appendChild(provNote);
    }

    const saveBtn = document.createElement("button");
    saveBtn.className = "settings-save-btn";
    saveBtn.textContent = "Save settings";
    const statusEl = document.createElement("div");
    statusEl.className = "settings-save-status";
    saveBtn.addEventListener("click", function () {
      saveSettingsProfile(
        {
          system_prompt: promptInput.value,
          mode: modeSelect.value,
          preferred_provider: provSelect.value, // "" → cleared (null) on the server
        },
        statusEl,
        saveBtn
      );
    });
    body.appendChild(saveBtn);
    body.appendChild(statusEl);

    // --- Voice (M30.6) — per-BROWSER prefs, applied instantly (localStorage).
    // Deliberately separate from the server-persisted "Save settings" above.
    body.appendChild(_settingsSectionTitle("Voice"));
    const vp = getVoicePrefs();
    body.appendChild(_voiceToggleRow("Speak responses aloud", "speak", vp.speak));

    const voiceSelect = document.createElement("select");
    voiceSelect.className = "settings-edit-select";
    function _populateVoices() {
      const current = getVoicePrefs().voiceName || "";
      voiceSelect.textContent = "";
      const def = document.createElement("option");
      def.value = "";
      def.textContent = "(browser default)";
      voiceSelect.appendChild(def);
      const voices = typeof voice !== "undefined" ? voice.listVoices() : [];
      voices.forEach(function (v) {
        const o = document.createElement("option");
        o.value = v.name;
        o.textContent = v.name + (v.lang ? " (" + v.lang + ")" : "");
        voiceSelect.appendChild(o);
      });
      voiceSelect.value = current;
      if (voiceSelect.value !== current) voiceSelect.value = ""; // voice vanished
    }
    _populateVoices();
    // Voices load asynchronously in some browsers — repopulate when they land.
    if (typeof voice !== "undefined" && voice.isTTSSupported &&
        window.speechSynthesis && window.speechSynthesis.addEventListener) {
      try {
        window.speechSynthesis.addEventListener("voiceschanged", _populateVoices, { once: true });
      } catch (_) {}
    }
    voiceSelect.addEventListener("change", function () {
      setVoicePref("voiceName", voiceSelect.value);
    });
    body.appendChild(_settingsControlRow("Voice", voiceSelect));

    body.appendChild(_voiceToggleRow("Auto-send voice transcript", "autoSend", vp.autoSend));
    body.appendChild(_voiceToggleRow("Keep listening until stopped", "continuous", vp.continuous));
    const voiceNote = document.createElement("div");
    voiceNote.className = "settings-note";
    voiceNote.textContent =
      "Voice settings apply immediately and are saved in this browser (not the profile).";
    body.appendChild(voiceNote);

    // --- Read-only context (not editable in this milestone) ---
    body.appendChild(_settingsSectionTitle("Tools"));
    const tools = Array.isArray(p.allowed_tools) ? p.allowed_tools : [];
    body.appendChild(_settingsRow("Allowed", tools.length ? tools.join(", ") : "none"));

    body.appendChild(_settingsSectionTitle("Memory"));
    body.appendChild(_settingsRow("Auto-save threshold", memory.auto_save_threshold));
    const review = Array.isArray(memory.require_review_for) ? memory.require_review_for : [];
    body.appendChild(_settingsRow("Review required for", review.length ? review.join(", ") : "none"));
  } catch (_) {
    _settingsMessage(body, "Failed to load profile.", "settings-error");
  }
}

function _settingsSelect(options, current) {
  const sel = document.createElement("select");
  sel.className = "settings-edit-select";
  const cur = current || "";
  options.forEach(function (opt) {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    if (opt.value === cur) o.selected = true;
    sel.appendChild(o);
  });
  return sel;
}

/** M30.6: one instant-apply voice-pref checkbox row (localStorage-backed). */
function _voiceToggleRow(label, prefKey, checked) {
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = !!checked;
  cb.addEventListener("change", function () {
    setVoicePref(prefKey, cb.checked);
  });
  return _settingsControlRow(label, cb);
}

function _settingsControlRow(key, controlEl) {
  const row = document.createElement("div");
  row.className = "settings-row";
  const k = document.createElement("span");
  k.className = "settings-key";
  k.textContent = key;
  controlEl.classList.add("settings-val");
  row.appendChild(k);
  row.appendChild(controlEl);
  return row;
}

async function saveSettingsProfile(payload, statusEl, btn) {
  btn.disabled = true;
  statusEl.textContent = "Saving…";
  statusEl.className = "settings-save-status";
  try {
    const res = await fetch("/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      // Re-render the Profile tab from the canonical persisted /profile so the
      // user sees the saved values, not optimistic local DOM state (M26.1).
      // M26.10: only if the user is still on the Profile tab — otherwise this
      // would clobber whatever tab they switched to during the PATCH.
      if (_activeSettingsTab !== "profile") return;
      await loadSettingsProfile();
      const fresh = document.querySelector("#settings-panel-body .settings-save-status");
      if (fresh) {
        fresh.textContent = "Saved. Changes apply to new messages.";
        fresh.className = "settings-save-status settings-save-ok";
      }
      return;
    }
    let detail = "Save failed (" + res.status + ").";
    try {
      const err = await res.json();
      if (err && err.detail) detail = err.detail;
    } catch (_) {}
    statusEl.textContent = detail;
    statusEl.className = "settings-save-status settings-save-error";
  } catch (_) {
    statusEl.textContent = "Network error — could not save.";
    statusEl.className = "settings-save-status settings-save-error";
  } finally {
    btn.disabled = false;
  }
}

async function loadSettingsProviders() {
  const body = document.getElementById("settings-panel-body");
  const token = ++_panelLoadToken.settings;
  body.textContent = "";
  try {
    const res = await fetch("/providers");
    if (token !== _panelLoadToken.settings) return; // superseded by a newer load
    if (!res.ok) {
      _settingsMessage(body, "Failed to load providers.", "settings-error");
      return;
    }
    const providers = await res.json();
    if (token !== _panelLoadToken.settings) return;
    if (!Array.isArray(providers) || providers.length === 0) {
      _settingsMessage(body, "No providers configured.");
      return;
    }
    body.appendChild(_settingsSectionTitle("Providers"));
    providers.forEach(function (p) {
      const availClass = p.available ? "ok" : "bad";
      const status =
        (p.enabled ? "enabled" : "disabled") + " · " + (p.available ? "available" : "unavailable");
      const label = p.name + "  (" + (p.cost_tier || "?") + "/" + (p.type || "?") + ")";
      body.appendChild(_settingsRow(label, status, availClass));
    });
  } catch (_) {
    _settingsMessage(body, "Failed to load providers.", "settings-error");
  }
}

async function loadSettingsIntegrations() {
  const body = document.getElementById("settings-panel-body");
  const token = ++_panelLoadToken.settings;
  body.textContent = "";
  try {
    const res = await fetch("/status/dav");
    if (token !== _panelLoadToken.settings) return; // superseded by a newer load
    if (!res.ok) {
      _settingsMessage(body, "Failed to load integration status.", "settings-error");
      return;
    }
    const data = await res.json();
    if (token !== _panelLoadToken.settings) return;
    const names = data && typeof data === "object" ? Object.keys(data) : [];
    if (names.length === 0) {
      _settingsMessage(body, "No integration status available.");
      return;
    }
    names.forEach(function (name) {
      const s = data[name] || {};
      body.appendChild(_settingsSectionTitle(name));
      Object.keys(s).forEach(function (key) {
        const val = s[key];
        if (Array.isArray(val)) {
          body.appendChild(_settingsRow(key, val.length ? val.join(", ") : "none"));
        } else if (val === null || typeof val !== "object") {
          // Highlight reachability/enabled-style booleans in green/red.
          let cls = "";
          if (key === "reachable" || key === "enabled" || key === "ok") {
            cls = val ? "ok" : "bad";
          }
          body.appendChild(_settingsRow(key, val, cls));
        }
        // nested objects (e.g. item_counts) are skipped in this read-only view
      });
    });
  } catch (_) {
    _settingsMessage(body, "Failed to load integration status.", "settings-error");
  }
}


/* ---------------------------------------------------------
   History & Attachments panel — open / close / switch (M20)
   Read-only; mirrors the memory/settings panels. History is
   the current in-memory session only; Files is a read-only
   browse of allowlisted files. One panel open at a time.
   --------------------------------------------------------- */
let _activeHistoryTab = "conversation";

function openHistoryPanel() {
  document.getElementById("memory-panel").classList.add("hidden");
  document.getElementById("settings-panel").classList.add("hidden");
  document.getElementById("history-panel").classList.remove("hidden");
  loadHistoryTab(_activeHistoryTab);
}

function closeHistoryPanel() {
  document.getElementById("history-panel").classList.add("hidden");
}

function switchHistoryTab(tab) {
  _activeHistoryTab = tab;
  document.querySelectorAll(".hist-tab").forEach(function (btn) {
    if (btn.dataset.tab === tab) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });
  loadHistoryTab(tab);
}

function loadHistoryTab(tab) {
  if (tab === "files") {
    loadHistoryFiles();
  } else {
    loadHistoryConversation();
  }
}


/* ---------------------------------------------------------
   History tab — current session conversation (read-only)
   Renders from the live message DOM (the rendered in-memory
   session); clicking an item scrolls to that message. No new
   storage or message model is introduced.
   --------------------------------------------------------- */
function loadHistoryConversation() {
  const body = document.getElementById("history-panel-body");
  // M26.10: bump the token even though this loader is synchronous, so an
  // in-flight Files fetch is superseded and can't append over this content.
  ++_panelLoadToken.history;
  body.textContent = "";

  const wrappers = messagesEl ? messagesEl.querySelectorAll(".message-wrapper") : [];

  // Toolbar: message count + clear action
  const toolbar = document.createElement("div");
  toolbar.className = "history-toolbar";
  const count = document.createElement("span");
  count.textContent = wrappers.length + (wrappers.length === 1 ? " message" : " messages");
  const clearBtn = document.createElement("button");
  clearBtn.className = "history-clear-btn";
  clearBtn.textContent = "Clear conversation";
  clearBtn.addEventListener("click", clearConversation);
  toolbar.appendChild(count);
  toolbar.appendChild(clearBtn);
  body.appendChild(toolbar);

  if (wrappers.length === 0) {
    _historyMessage(body, "No messages yet.");
    return;
  }

  wrappers.forEach(function (wrapper) {
    const role = wrapper.classList.contains("message-user")
      ? "you"
      : wrapper.classList.contains("message-error")
      ? "error"
      : "assistant";
    const bubble = wrapper.querySelector(".bubble");
    const text = bubble ? bubble.textContent : "";

    const item = document.createElement("div");
    item.className = "history-item";

    const roleEl = document.createElement("div");
    roleEl.className = "history-role";
    roleEl.textContent = role;

    const previewEl = document.createElement("div");
    previewEl.className = "history-preview";
    previewEl.textContent = text;

    item.appendChild(roleEl);
    item.appendChild(previewEl);
    item.addEventListener("click", function () {
      wrapper.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    body.appendChild(item);
  });

  _appendPastConversations(body);
}

/**
 * M29.1 — list persisted conversations under the live view; click restores one
 * into the chat (and resumes appending to it). Token-guarded like every async
 * panel loader (M26.10).
 */
async function _appendPastConversations(body) {
  const token = _panelLoadToken.history;
  let convs = [];
  try {
    const res = await fetch("/history/conversations");
    if (res.ok) convs = await res.json();
  } catch (_) {
    return; // history unavailable — panel simply shows the live view only
  }
  if (token !== _panelLoadToken.history) return; // superseded
  if (!Array.isArray(convs) || convs.length === 0) return;

  const title = document.createElement("div");
  title.className = "history-role";
  title.textContent = "Past conversations";
  body.appendChild(title);

  convs.forEach(function (c) {
    const item = document.createElement("div");
    item.className = "history-item";
    const roleEl = document.createElement("div");
    roleEl.className = "history-role";
    roleEl.textContent = (c.started_at || c.id) + " · " + c.turns + " turns";
    const previewEl = document.createElement("div");
    previewEl.className = "history-preview";
    previewEl.textContent = c.preview || "(no preview)";
    item.appendChild(roleEl);
    item.appendChild(previewEl);
    item.addEventListener("click", function () {
      _loadPastConversation(c.id);
    });
    // M29.4: per-conversation Markdown export (browser downloads the file).
    const exportBtn = document.createElement("button");
    exportBtn.className = "history-clear-btn";
    exportBtn.textContent = "Export";
    exportBtn.addEventListener("click", function (ev) {
      ev.stopPropagation(); // don't also load the conversation
      window.open("/history/conversations/" + encodeURIComponent(c.id) + "/export");
    });
    item.appendChild(exportBtn);
    body.appendChild(item);
  });
}

/** Restore a persisted conversation into the chat window and resume it. */
async function _loadPastConversation(id) {
  let data;
  try {
    const res = await fetch("/history/conversations/" + encodeURIComponent(id));
    if (!res.ok) return;
    data = await res.json();
  } catch (_) {
    return;
  }
  const turns = Array.isArray(data.turns) ? data.turns : [];
  conversationHistory = [];
  conversationId = id;
  if (messagesEl) messagesEl.textContent = "";
  turns.forEach(function (t) {
    if (t.role !== "user" && t.role !== "assistant") return;
    // Failed assistant turns render as errors and are NOT replayed as context
    // (the M26.10 rule, applied to restored history too).
    if (t.role === "assistant" && t.success === false) {
      appendMessage("error", t.content || "", t.provider || null, t.model || null);
      return;
    }
    conversationHistory.push({ role: t.role, content: t.content || "" });
    appendMessage(t.role, t.content || "", t.provider || null, t.model || null);
  });
  document.getElementById("history-panel").classList.add("hidden");
}

function clearConversation() {
  conversationHistory = [];
  conversationId = null; // M29.1: next send starts a fresh persisted conversation
  if (messagesEl) {
    messagesEl.textContent = "";
  }
  appendMessage(
    "assistant",
    "Hello. I'm " + assistantName + ". How can I help?",
    null,
    null,
    /* isWelcome */ true
  );
  // Refresh the (now-empty) history list.
  loadHistoryConversation();
}


/* ---------------------------------------------------------
   Files tab — read-only browse of allowlisted files (M20)
   Shallow listing via POST /files/search ("*"); click to
   preview content via GET /files/read. Not a file manager.
   --------------------------------------------------------- */
async function loadHistoryFiles(showInternal) {
  const body = document.getElementById("history-panel-body");
  const token = ++_panelLoadToken.history;
  body.textContent = "";

  // Toolbar is always shown (even on empty results) so the ops toggle is
  // reachable. Default hides internal/ops files (M26.3).
  const toolbar = document.createElement("div");
  toolbar.className = "history-toolbar";
  const count = document.createElement("span");
  count.className = "history-count";
  const toggle = document.createElement("label");
  toggle.className = "history-ops-toggle";
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = !!showInternal;
  cb.addEventListener("change", function () {
    loadHistoryFiles(cb.checked);
  });
  toggle.appendChild(cb);
  toggle.appendChild(document.createTextNode(" Show internal/ops files"));
  toolbar.appendChild(count);
  toolbar.appendChild(toggle);
  body.appendChild(toolbar);

  if (showInternal) {
    const note = document.createElement("div");
    note.className = "history-ops-note";
    note.textContent = "Showing internal/operational files";
    body.appendChild(note);
  }

  try {
    // M30.4: the shallow "*" listing plus one level into uploads/, so
    // uploaded files are visible without turning the panel into a full
    // recursive tree. The uploads fetch is best-effort — its failure must
    // never break the primary listing.
    function search(pattern) {
      return fetch("/files/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pattern: pattern, exclude_internal: !showInternal }),
      });
    }
    const [res, resUploads] = await Promise.all([
      search("*"),
      search("uploads/*").catch(function () { return null; }),
    ]);
    if (token !== _panelLoadToken.history) return; // superseded by a newer load
    if (!res.ok) {
      _historyMessage(body, "Failed to list files.", "history-error");
      return;
    }
    const paths = await res.json();
    if (resUploads && resUploads.ok) {
      try {
        const uploadPaths = await resUploads.json();
        if (Array.isArray(uploadPaths)) {
          uploadPaths.forEach(function (p) {
            if (paths.indexOf(p) === -1) paths.push(p);
          });
        }
      } catch (_) {
        // best-effort — the primary listing stands on its own
      }
    }
    if (token !== _panelLoadToken.history) return;
    if (!Array.isArray(paths) || paths.length === 0) {
      count.textContent = "0 files";
      _historyMessage(body, showInternal ? "No files found." : "No user files to show.");
      return;
    }
    count.textContent =
      paths.length + (paths.length === 1 ? " file" : " files") + " · click to preview";

    paths.forEach(function (path) {
      const item = document.createElement("div");
      item.className = "file-item";
      item.textContent = path;
      item.addEventListener("click", function () {
        previewFile(path, body);
      });
      body.appendChild(item);
    });
  } catch (_) {
    _historyMessage(body, "Failed to list files.", "history-error");
  }
}

async function previewFile(path, body) {
  // Replace any existing preview.
  const existing = body.querySelector(".file-preview");
  if (existing) existing.remove();

  const pre = document.createElement("div");
  pre.className = "file-preview";
  pre.textContent = "Loading " + path + " ...";
  body.appendChild(pre);

  try {
    const res = await fetch("/files/read?path=" + encodeURIComponent(path));
    if (!res.ok) {
      pre.textContent = "Cannot preview " + path + " (" + res.status + ").";
      return;
    }
    const data = await res.json();
    pre.textContent = data && typeof data.content === "string" ? data.content : "(no content)";
  } catch (_) {
    pre.textContent = "Failed to read " + path + ".";
  }
}

function _historyMessage(body, text, cls) {
  const el = document.createElement("div");
  el.className = cls || "history-empty";
  el.textContent = text;
  body.appendChild(el);
}
