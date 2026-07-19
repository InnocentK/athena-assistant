// tests/js/conversationMode.test.js — M31.0 conversation mode.
// Streaming speech (sentence enqueue), the hands-free loop, and barge-in.
// Drives the shipped chat.js + voice.js in jsdom with fake speech APIs; the
// M30.6 suites pin that everything here is inert while the toggle is OFF.

import { beforeEach, describe, expect, test, vi } from "vitest";
import { bootChat, renderedMessages } from "./loadChat.js";

const PREFS_KEY = "athena-voice-prefs";

class FakeUtterance {
  constructor(text) {
    this.text = text;
    this.voice = null;
    this.rate = 1.0;
    this.pitch = 1.0;
    this.volume = 1.0;
    this.onend = null;
  }
}

class FakeRecognition {
  constructor() {
    FakeRecognition.last = this;
    FakeRecognition.count = (FakeRecognition.count || 0) + 1;
    this.continuous = false;
    this.interimResults = false;
    this.lang = "";
  }
  start() {}
  stop() {
    if (this.onend) this.onend();
  }
}

function installSpeechFakes() {
  const speakSpy = vi.fn();
  const cancelSpy = vi.fn();
  window.speechSynthesis = {
    speak: speakSpy,
    cancel: cancelSpy,
    getVoices: () => [{ name: "TestVoice", lang: "en-US" }],
    addEventListener: vi.fn(),
  };
  window.SpeechSynthesisUtterance = FakeUtterance;
  globalThis.SpeechSynthesisUtterance = FakeUtterance;
  window.webkitSpeechRecognition = FakeRecognition;
  FakeRecognition.count = 0;
  FakeRecognition.last = null;
  return { speakSpy, cancelSpy };
}

function sseStream(parts) {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      parts.forEach((p) => controller.enqueue(enc.encode(p)));
      controller.close();
    },
  });
}

function frame(event, payload) {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

function streamFetch(streamParts) {
  return (url, opts) => {
    if (typeof url === "string" && url.includes("/chat/stream")) {
      return Promise.resolve({ ok: true, status: 200, body: sseStream(streamParts || []) });
    }
    if (typeof url === "string" && url.includes("/chat") && opts && opts.method === "POST") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ success: true, response: "buffered answer", provider: "p", model: "m" }),
      });
    }
    const body = String(url).includes("/providers") ? [] : { name: "Athena", routing: {} };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  };
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async (n = 6) => { for (let i = 0; i < n; i++) await tick(); };

async function send(chat, text) {
  document.getElementById("message-input").value = text;
  await chat.sendMessage();
}

function spokenTexts(speakSpy) {
  return speakSpy.mock.calls.map((c) => c[0].text);
}

beforeEach(() => {
  window.localStorage.clear();
});

/* ---------------------------------------------------------------- */
describe("M31.0 — sentence splitter", () => {
  let split;
  beforeEach(async () => {
    installSpeechFakes();
    const { chat } = await bootChat(streamFetch([]));
    split = chat._splitCompleteSentences;
  });

  test("splits at terminator + whitespace, keeps the unconfirmed tail", () => {
    expect(split("First sentence here. Second part")).toEqual({
      sentences: ["First sentence here."],
      rest: " Second part",
    });
  });

  test("never splits at end-of-buffer (the next chunk could continue it)", () => {
    expect(split("A complete looking sentence.")).toEqual({
      sentences: [],
      rest: "A complete looking sentence.",
    });
  });

  test("min-length guard: abbreviations and short bursts do not fire", () => {
    expect(split("e.g. cats").sentences).toEqual([]);
    expect(split("What?! ok").sentences).toEqual([]);
  });

  test("short sentences merge forward into one utterance", () => {
    expect(split("Yes. But actually there is more. x")).toEqual({
      sentences: ["Yes. But actually there is more."],
      rest: " x",
    });
  });

  test("decimal points are not boundaries", () => {
    expect(split("Pi is 3.14 exactly. Neat")).toEqual({
      sentences: ["Pi is 3.14 exactly."],
      rest: " Neat",
    });
  });

  test("multiple completed sentences come out in order", () => {
    expect(split("One full sentence here. Two full sentences here! And")).toEqual({
      sentences: ["One full sentence here.", "Two full sentences here!"],
      rest: " And",
    });
  });
});

/* ---------------------------------------------------------------- */
describe("M31.0 — _shouldSpeak (A2)", () => {
  test("conversation mode implies speaking; stored prefs are respected", async () => {
    installSpeechFakes();
    const { chat } = await bootChat(streamFetch([]));
    expect(chat._shouldSpeak({ speak: false, conversation: false })).toBe(false);
    expect(chat._shouldSpeak({ speak: true, conversation: false })).toBe(true);
    expect(chat._shouldSpeak({ speak: false, conversation: true })).toBe(true);
  });
});

/* ---------------------------------------------------------------- */
const S1 = "First sentence is long enough.";
const S2 = "Second sentence also long enough!";
const TAIL = "Short tail";
const FULL = `${S1} ${S2} ${TAIL}`;

describe("M31.0 — streaming speech", () => {
  test("ON: sentences are enqueued as chunks complete them; tail flushes at done", async () => {
    const { speakSpy, cancelSpy } = installSpeechFakes();
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ conversation: true }));
    const { chat } = await bootChat(
      streamFetch([
        frame("chunk", { text: `${S1} Sec` }),
        frame("chunk", { text: `ond sentence also long enough! ${TAIL}` }),
        frame("done", { success: true, response: FULL, provider: "p", model: null, conversation_id: null, diagnostics: null, error: null }),
      ])
    );

    await send(chat, "hi");

    // Spoken exactly once each, in order — nothing re-spoken at done.
    expect(spokenTexts(speakSpy)).toEqual([S1, S2, TAIL]);
    // enqueue never cancels: the only cancel is sendMessage's barge-in.
    expect(cancelSpy).toHaveBeenCalledTimes(1);
    // The rendered answer is intact and recorded once.
    expect(chat.conversationHistory[1]).toEqual({ role: "assistant", content: FULL });
  });

  test("ON: the authoritative-text reconcile is visual-only, never spoken", async () => {
    const { speakSpy } = installSpeechFakes();
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ conversation: true }));
    const assembled = "Streamed text without terminator";
    const canonical = "Canonical different text.";
    const { chat } = await bootChat(
      streamFetch([
        frame("chunk", { text: assembled }),
        frame("done", { success: true, response: canonical, provider: "p", model: null, conversation_id: null, diagnostics: null, error: null }),
      ])
    );

    await send(chat, "hi");

    // The bubble shows the reconciled canonical text…
    const assistants = renderedMessages().filter((m) => m.role === "assistant");
    expect(assistants[assistants.length - 1].text).toBe(canonical);
    // …but speech got the streamed tail only (what the user watched arrive).
    expect(spokenTexts(speakSpy)).toEqual([assembled]);
  });

  test("OFF with speak:true: the M30.6 whole-reply path is unchanged", async () => {
    const { speakSpy } = installSpeechFakes();
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ speak: true, voiceName: "TestVoice" }));
    const { chat } = await bootChat(
      streamFetch([
        frame("chunk", { text: FULL }),
        frame("done", { success: true, response: FULL, provider: "p", model: null, conversation_id: null, diagnostics: null, error: null }),
      ])
    );

    await send(chat, "hi");

    expect(spokenTexts(speakSpy)).toEqual([FULL]); // ONE utterance, whole reply
    expect(speakSpy.mock.calls[0][0].voice.name).toBe("TestVoice");
  });
});

/* ---------------------------------------------------------------- */
describe("M31.0 — hands-free loop + barge-in", () => {
  async function bootConversation(streamParts) {
    const spies = installSpeechFakes();
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ conversation: true }));
    const booted = await bootChat(streamFetch(streamParts));
    return Object.assign({}, booted, spies, { ptt: document.getElementById("ptt-btn") });
  }

  function _stopMic() {
    // Close the recognition session browser-side (without the pttBtn click,
    // which would deliberately disarm the loop).
    if (FakeRecognition.last && FakeRecognition.last.onend) FakeRecognition.last.onend();
  }

  const DONE = { success: true, response: FULL, provider: "p", model: null, conversation_id: null, diagnostics: null, error: null };

  test("a mic click arms the loop (visual state); transcript auto-sends (A1) with barge-in cancel", async () => {
    const { cancelSpy, ptt, fetchCalls } = await bootConversation([
      frame("chunk", { text: FULL }),
      frame("done", DONE),
    ]);

    ptt.click(); // the user gesture that arms the loop
    expect(ptt.classList.contains("conversation-live")).toBe(true);
    expect(window.voice.isListening).toBe(true);

    window.voice.onTranscript("question one"); // delivered transcript…
    FakeRecognition.last.onend();              // …and the browser closes the session
    await settle();

    // barge-in: cancel fired on transcript delivery (and again on send)
    expect(cancelSpy.mock.calls.length).toBeGreaterThanOrEqual(1);
    // A1: auto-sent without the stored autoSend pref
    expect(fetchCalls.some((c) => String(c.url).includes("/chat/stream"))).toBe(true);
  });

  test("mic re-opens after the last utterance ends; loop survives multiple turns", async () => {
    const { speakSpy, ptt } = await bootConversation([
      frame("chunk", { text: FULL }),
      frame("done", DONE),
    ]);

    ptt.click();
    const firstRec = FakeRecognition.last;
    window.voice.onTranscript("question one");
    firstRec.onend();
    await settle();

    // Reply spoken; mic still closed while speaking.
    expect(speakSpy.mock.calls.length).toBeGreaterThan(0);
    expect(window.voice.isListening).toBe(false);

    // Fire speech-end events in queue order → the LAST one re-opens the mic.
    spokenTexts(speakSpy); // (materialize before iterating)
    speakSpy.mock.calls.forEach((c) => c[0].onend && c[0].onend());
    await settle();

    expect(FakeRecognition.last).not.toBe(firstRec); // a NEW session started
    expect(window.voice.isListening).toBe(true);
    expect(ptt.classList.contains("conversation-live")).toBe(true);
  });

  test("a typed send exits the loop: no auto-reopen after speech ends", async () => {
    const { speakSpy, chat, ptt } = await bootConversation([
      frame("chunk", { text: FULL }),
      frame("done", DONE),
    ]);

    ptt.click();
    _stopMic();
    expect(ptt.classList.contains("conversation-live")).toBe(true);

    await send(chat, "typed message"); // modality switch
    expect(ptt.classList.contains("conversation-live")).toBe(false);

    const recBefore = FakeRecognition.count;
    speakSpy.mock.calls.forEach((c) => c[0].onend && c[0].onend());
    await settle();
    expect(FakeRecognition.count).toBe(recBefore); // mic stayed closed
    expect(window.voice.isListening).toBe(false);
  });

  test("an STT error exits the loop", async () => {
    const { ptt } = await bootConversation([]);
    ptt.click();
    expect(ptt.classList.contains("conversation-live")).toBe(true);

    FakeRecognition.last.onerror({ error: "no-speech" });
    expect(ptt.classList.contains("conversation-live")).toBe(false);
    const errors = renderedMessages().filter((m) => m.role === "error");
    expect(errors.length).toBe(1);
  });

  test("A3: a failed turn re-opens the mic immediately (conversational retry)", async () => {
    const { ptt } = await bootConversation([
      frame("done", { success: false, response: "", provider: "p", model: null, conversation_id: null, diagnostics: null, error: "provider died" }),
    ]);

    ptt.click();
    const firstRec = FakeRecognition.last;
    window.voice.onTranscript("question one");
    firstRec.onend();
    await settle();

    expect(renderedMessages().some((m) => m.role === "error")).toBe(true);
    expect(FakeRecognition.last).not.toBe(firstRec); // mic re-opened, no speech needed
    expect(window.voice.isListening).toBe(true);
  });

  test("losing tab visibility exits the loop", async () => {
    const { ptt } = await bootConversation([]);
    ptt.click();
    expect(ptt.classList.contains("conversation-live")).toBe(true);

    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    try {
      document.dispatchEvent(new window.Event("visibilitychange"));
      expect(ptt.classList.contains("conversation-live")).toBe(false);
    } finally {
      Object.defineProperty(document, "hidden", { value: false, configurable: true });
    }
  });

  test("unchecking Conversation mode in Settings disarms a live loop", async () => {
    const { ptt } = await bootConversation([]);
    ptt.click();
    _stopMic();
    expect(ptt.classList.contains("conversation-live")).toBe(true);

    document.getElementById("settings-btn").click();
    await settle();
    const rows = Array.from(document.querySelectorAll("#settings-panel-body .settings-row"));
    const row = rows.find((r) => {
      const k = r.querySelector(".settings-key");
      return k && k.textContent === "Conversation mode";
    });
    expect(row).toBeTruthy();
    const cb = row.querySelector("input[type=checkbox]");
    expect(cb.checked).toBe(true);
    cb.click(); // → unchecked → onChange(false) disarms

    expect(JSON.parse(window.localStorage.getItem(PREFS_KEY)).conversation).toBe(false);
    expect(ptt.classList.contains("conversation-live")).toBe(false);
  });
});

/* ---------------------------------------------------------------- */
describe("M31.2 — audible turn indicator", () => {
  // NOTE: every M31.0 loop test above runs WITHOUT an AudioContext fake —
  // their continued passing is the no-Web-Audio degradation proof.
  class FakeAudioContext {
    constructor() {
      FakeAudioContext.last = this;
      this.state = "running";
      this.currentTime = 0;
      this.destination = {};
      this.oscillators = 0;
    }
    resume() {
      this.state = "running";
    }
    createOscillator() {
      this.oscillators++;
      return {
        type: "",
        frequency: { value: 0 },
        connect: (n) => n,
        start() {},
        stop() {},
      };
    }
    createGain() {
      return {
        gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
        connect: (n) => n,
      };
    }
  }

  async function bootWithAudio(streamParts, prefs) {
    const spies = installSpeechFakes();
    FakeAudioContext.last = null;
    window.AudioContext = FakeAudioContext;
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    const booted = await bootChat(streamFetch(streamParts));
    return Object.assign({}, booted, spies, { ptt: document.getElementById("ptt-btn") });
  }

  const DONE = { success: true, response: FULL, provider: "p", model: null, conversation_id: null, diagnostics: null, error: null };

  test("auto-reopen blips; the arming click itself does not", async () => {
    const { speakSpy, ptt } = await bootWithAudio(
      [frame("chunk", { text: FULL }), frame("done", DONE)],
      { conversation: true }
    );

    ptt.click(); // gesture: unlocks the context, arms the loop — no blip
    expect(FakeAudioContext.last).toBeTruthy();
    expect(FakeAudioContext.last.oscillators).toBe(0);

    window.voice.onTranscript("question one");
    FakeRecognition.last.onend();
    await settle();
    speakSpy.mock.calls.forEach((c) => c[0].onend && c[0].onend());
    await settle();

    expect(window.voice.isListening).toBe(true); // loop re-opened…
    expect(FakeAudioContext.last.oscillators).toBe(2); // …with the two-tone blip
  });

  test("conversation OFF: a dictation mic click creates no AudioContext", async () => {
    const { ptt } = await bootWithAudio([], { conversation: false });
    ptt.click();
    expect(window.voice.isListening).toBe(true); // plain M30.6 dictation
    expect(FakeAudioContext.last).toBe(null); // no unlock, no context
  });
});
