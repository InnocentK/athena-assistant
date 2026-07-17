// tests/js/voicePrefs.test.js — M30.6 voice preferences.
// Injects fake speechSynthesis / SpeechRecognition BEFORE booting the shipped
// scripts, so voice.js detects support and chat.js's pref gates are real.

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
  }
}

class FakeRecognition {
  constructor() {
    FakeRecognition.last = this;
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
  window.speechSynthesis = {
    speak: speakSpy,
    cancel: vi.fn(),
    getVoices: () => [{ name: "TestVoice", lang: "en-US" }],
    addEventListener: vi.fn(),
  };
  window.SpeechSynthesisUtterance = FakeUtterance;
  window.webkitSpeechRecognition = FakeRecognition;
  globalThis.SpeechSynthesisUtterance = FakeUtterance;
  return speakSpy;
}

// fetch: /chat/stream 404s → buffered /chat answers (the simplest success path)
function chatFetch() {
  return (url, opts) => {
    if (typeof url === "string" && url.includes("/chat/stream")) {
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    }
    if (typeof url === "string" && url.includes("/chat") && opts && opts.method === "POST") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ success: true, response: "spoken answer", provider: "p", model: "m" }),
      });
    }
    const body = url.includes("/providers") ? [] : { name: "Athena", routing: {} };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  };
}

async function send(chat, text) {
  document.getElementById("message-input").value = text;
  await chat.sendMessage();
}

const tick = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  window.localStorage.clear();
});

describe("M30.6 — speak-responses is opt-in", () => {
  test("default: a successful answer is NOT read aloud", async () => {
    const speakSpy = installSpeechFakes();
    const { chat } = await bootChat(chatFetch());

    await send(chat, "hi");

    expect(chat.conversationHistory[1].content).toBe("spoken answer"); // answered
    expect(speakSpy).not.toHaveBeenCalled();                            // silent
  });

  test("speak:true pref reads the answer with the chosen voice", async () => {
    const speakSpy = installSpeechFakes();
    window.localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({ speak: true, voiceName: "TestVoice" })
    );
    const { chat } = await bootChat(chatFetch());

    await send(chat, "hi");

    expect(speakSpy).toHaveBeenCalledTimes(1);
    const utterance = speakSpy.mock.calls[0][0];
    expect(utterance.text).toBe("spoken answer");
    expect(utterance.voice && utterance.voice.name).toBe("TestVoice");
  });
});

describe("M30.6 — transcript auto-send is opt-in", () => {
  test("default: the transcript lands in the input and nothing is sent", async () => {
    installSpeechFakes();
    const { fetchCalls } = await bootChat(chatFetch());
    const before = fetchCalls.filter((c) => String(c.url).includes("/chat")).length;

    window.voice.onTranscript("dictated text");
    await tick();
    await tick();

    expect(document.getElementById("message-input").value).toBe("dictated text");
    const after = fetchCalls.filter((c) => String(c.url).includes("/chat")).length;
    expect(after).toBe(before); // no send
  });

  test("autoSend:true sends the transcript immediately", async () => {
    installSpeechFakes();
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ autoSend: true }));
    const { chat, fetchCalls } = await bootChat(chatFetch());

    window.voice.onTranscript("dictated text");
    await tick();
    await tick();
    await tick();

    expect(chat.conversationHistory[0]).toEqual({ role: "user", content: "dictated text" });
    expect(fetchCalls.some((c) => String(c.url).includes("/chat"))).toBe(true);
  });
});

describe("M30.6 — continuous mic mode", () => {
  test("continuous mode accumulates finals and delivers once on stop", async () => {
    installSpeechFakes();
    await bootChat(chatFetch());

    const got = [];
    window.voice.onTranscript = (t) => got.push(t);
    window.voice.continuous = true;
    window.voice.startListening();

    const rec = FakeRecognition.last;
    expect(rec.continuous).toBe(true);
    const final = (text) => {
      const r = [{ transcript: text }];
      r.isFinal = true;
      return r;
    };
    rec.onresult({ resultIndex: 0, results: [final("part one")] });
    rec.onresult({ resultIndex: 1, results: [final("part one"), final("part two")] });
    expect(got).toHaveLength(0); // nothing delivered mid-session

    window.voice.stopListening(); // triggers onend
    expect(got).toEqual(["part one part two"]);
  });

  test("default (non-continuous) still delivers on first result", async () => {
    installSpeechFakes();
    await bootChat(chatFetch());

    const got = [];
    window.voice.onTranscript = (t) => got.push(t);
    window.voice.continuous = false;
    window.voice.startListening();

    const rec = FakeRecognition.last;
    expect(rec.continuous).toBe(false);
    rec.onresult({ results: [[{ transcript: "quick note" }]] });
    expect(got).toEqual(["quick note"]);
  });
});

describe("M30.8 — voice test button", () => {
  test("Test voice speaks the sample phrase even with speak-responses OFF", async () => {
    const speakSpy = installSpeechFakes();
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ speak: false, voiceName: "TestVoice" }));
    const { chat } = await bootChat(chatFetch());

    // Open the settings Profile tab so the Voice section renders.
    document.getElementById("settings-btn").click();
    await tick();
    await tick();
    await tick();
    await tick();

    const buttons = Array.from(document.querySelectorAll("#settings-panel-body button"));
    const testBtn = buttons.find((b) => b.textContent === "Test voice");
    expect(testBtn).toBeTruthy();

    testBtn.click();
    expect(speakSpy).toHaveBeenCalledTimes(1);
    const utterance = speakSpy.mock.calls[0][0];
    expect(utterance.text).toBe("Hello. I'm Athena. How can I help?");
    expect(utterance.voice && utterance.voice.name).toBe("TestVoice");
  });
});
