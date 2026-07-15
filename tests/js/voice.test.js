// tests/js/voice.test.js — voice.js degrades safely where the browser speech
// APIs are absent (jsdom has neither speechSynthesis nor SpeechRecognition),
// which is the condition chat.js's `typeof voice` guards rely on (M26.10).

import { describe, expect, test } from "vitest";
import { bootChat, lastBubbleText } from "./loadChat.js";

describe("voice controller (unsupported environment)", () => {
  test("exposes a global `voice` with support flags false in jsdom", async () => {
    await bootChat();
    expect(typeof window.voice).toBe("object");
    expect(window.voice.isTTSSupported).toBe(false);   // no window.speechSynthesis
    expect(window.voice.isSupported).toBe(false);       // no SpeechRecognition
  });

  test("speak()/cancelSpeech() are safe no-ops when TTS is unsupported", async () => {
    await bootChat();
    expect(() => window.voice.speak("anything")).not.toThrow();
    expect(() => window.voice.cancelSpeech()).not.toThrow();
  });

  test("a successful answer still renders when voice is present but unsupported", async () => {
    // chat.js guards voice.speak with `voice.isTTSSupported`; the answer must
    // render regardless (the M26.10 'voice can't break the answer' guarantee).
    const { chat } = await bootChat((url, opts) => {
      if (String(url).includes("/chat") && opts && opts.method === "POST") {
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve({ success: true, response: "spoken?", provider: "claude", model: "m" }),
        });
      }
      const body = String(url).includes("/providers") ? [] : { name: "Athena", routing: {} };
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    });
    document.getElementById("message-input").value = "hi";
    await chat.sendMessage();
    expect(lastBubbleText("assistant")).toBe("spoken?");
  });
});
