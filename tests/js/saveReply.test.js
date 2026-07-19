// tests/js/saveReply.test.js — M31.3: the per-reply "Save" button.
// User-initiated save of an assistant reply through the EXISTING
// /files/upload envelope — no new endpoint, no model-initiated action.

import { describe, expect, test } from "vitest";
import { bootChat } from "./loadChat.js";

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

// fetch impl: streaming answers; /files/upload capturable + controllable.
function fetchWith({ streamParts, uploadResponder, buffered } = {}) {
  const uploads = [];
  const impl = (url, opts) => {
    const u = String(url);
    if (u.includes("/files/upload")) {
      uploads.push(opts);
      if (uploadResponder) return uploadResponder(url, opts);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ path: "data/uploads/reply-x.md" }),
      });
    }
    if (u.includes("/chat/stream")) {
      if (buffered) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
      return Promise.resolve({ ok: true, status: 200, body: sseStream(streamParts || []) });
    }
    if (u.includes("/chat") && opts && opts.method === "POST") {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ success: true, response: "buffered reply text", provider: "p", model: "m" }),
      });
    }
    const body = u.includes("/providers") ? [] : { name: "Athena", routing: {} };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  };
  impl.uploads = uploads;
  return impl;
}

const tick = () => new Promise((r) => setTimeout(r, 0));

// jsdom's File has no .text(); FileReader is the portable read path.
function readFileText(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsText(file);
  });
}

async function send(chat, text) {
  document.getElementById("message-input").value = text;
  await chat.sendMessage();
}

function lastSaveBtn() {
  const btns = document.querySelectorAll(".message-assistant .reply-save-btn");
  return btns.length ? btns[btns.length - 1] : null;
}

const REPLY = "Notes on Ganymede. It is the largest moon.";
const STREAMED = [
  frame("chunk", { text: REPLY }),
  frame("done", { success: true, response: REPLY, provider: "p", model: null, conversation_id: null, diagnostics: null, error: null }),
];

describe("M31.3 — save reply as file", () => {
  test("a streamed reply gets a Save button that uploads the reply as .md", async () => {
    const impl = fetchWith({ streamParts: STREAMED });
    const { chat } = await bootChat(impl);
    await send(chat, "jupiter notes");

    const btn = lastSaveBtn();
    expect(btn).toBeTruthy();
    btn.click();
    await tick();
    await tick();

    expect(impl.uploads).toHaveLength(1);
    const form = impl.uploads[0].body;
    expect(impl.uploads[0].method).toBe("POST");
    const file = form.get("file");
    expect(file).toBeTruthy();
    // filename: reply-YYYYMMDD-HHMMSS.md
    expect(file.name || form.get("file").name).toMatch(/^reply-\d{8}-\d{6}\.md$/);
    const content = await readFileText(file);
    expect(content).toBe(REPLY); // the authoritative rendered text, exactly
    expect(btn.textContent).toBe("Saved ✓");
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain("data/uploads/reply-x.md");
  });

  test("a buffered reply gets the button too; the welcome message never does", async () => {
    const impl = fetchWith({ buffered: true });
    const { chat } = await bootChat(impl);

    // welcome bubble exists but has no Save button (no meta at all)
    expect(document.querySelectorAll(".reply-save-btn")).toHaveLength(0);

    await send(chat, "hi");
    const btn = lastSaveBtn();
    expect(btn).toBeTruthy();
    btn.click();
    await tick();
    await tick();
    const content = await readFileText(impl.uploads[0].body.get("file"));
    expect(content).toBe("buffered reply text");
  });

  test("a failed save re-enables the button for retry; errors never get buttons", async () => {
    const impl = fetchWith({
      streamParts: STREAMED,
      uploadResponder: () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) }),
    });
    const { chat } = await bootChat(impl);
    await send(chat, "jupiter notes");

    const btn = lastSaveBtn();
    btn.click();
    await tick();
    await tick();
    expect(btn.textContent).toBe("Save failed");
    expect(btn.disabled).toBe(false); // retryable

    // failure turns (error bubbles) never carry a Save button
    const impl2 = fetchWith({
      streamParts: [frame("done", { success: false, response: "", provider: "p", model: null, conversation_id: null, diagnostics: null, error: "provider died" })],
    });
    const { chat: chat2 } = await bootChat(impl2);
    await send(chat2, "hi");
    expect(document.querySelectorAll(".message-error .reply-save-btn")).toHaveLength(0);
  });
});
