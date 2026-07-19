// tests/js/saveReply.test.js — M31.3/M31.4: the per-reply "Save" button.
// User-initiated save of an assistant reply — server copy through the
// EXISTING /files/upload envelope (dest=saved), and/or a client-side
// device download, per the browser-local "Saving replies" settings.

import { describe, expect, test, vi } from "vitest";
import { bootChat } from "./loadChat.js";

const SAVE_KEY = "athena-save-prefs";

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
        json: () => Promise.resolve({ path: "data/saved/reply-x.md" }),
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

function stubObjectURL() {
  const createSpy = vi.fn(() => "blob:athena-test");
  window.URL.createObjectURL = createSpy;
  window.URL.revokeObjectURL = vi.fn();
  // jsdom has no download flow — a real browser's `download` attribute
  // suppresses navigation, jsdom's doesn't. Neutralize the click so the
  // suite stays quiet; the unit under test is "anchor configured+clicked".
  vi.spyOn(window.HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  return createSpy;
}

const REPLY = "# Notes on Ganymede\nIt is the largest moon of Jupiter.";
const STREAMED = [
  frame("chunk", { text: REPLY }),
  frame("done", { success: true, response: REPLY, provider: "p", model: null, conversation_id: null, diagnostics: null, error: null }),
];

describe("M31.4 — derived filenames", () => {
  test("heading, first-words, and timestamp-fallback naming", async () => {
    const { chat } = await bootChat(fetchWith({ streamParts: [] }));
    const fn = chat._replyFilename;
    expect(fn("# Notes on Ganymede\nBody text.")).toBe("Notes-on-Ganymede.md");
    expect(fn("### Deep heading! ok\nx")).toBe("Deep-heading-ok.md");
    expect(fn("Jupiter is the fifth planet from the Sun and more words after"))
      .toBe("Jupiter-is-the-fifth-planet-from.md");
    expect(fn("???")).toMatch(/^reply-\d{8}-\d{6}\.md$/); // no usable slug
    expect(fn("")).toMatch(/^reply-\d{8}-\d{6}\.md$/);
  });
});

describe("M31.3/M31.4 — save reply destinations", () => {
  test("default (server on): uploads to dest=saved with the derived name", async () => {
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
    expect(form.get("dest")).toBe("saved");
    const file = form.get("file");
    expect(file.name).toBe("Notes-on-Ganymede.md");
    expect(await readFileText(file)).toBe(REPLY); // authoritative text, exactly
    expect(btn.textContent).toBe("Saved ✓");
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain("data/saved/reply-x.md");
  });

  test("device-only: downloads client-side, zero upload POSTs", async () => {
    window.localStorage.setItem(SAVE_KEY, JSON.stringify({ server: false, device: true }));
    const impl = fetchWith({ streamParts: STREAMED });
    const { chat } = await bootChat(impl);
    const createSpy = stubObjectURL();
    await send(chat, "jupiter notes");

    const btn = lastSaveBtn();
    btn.click();
    await tick();
    await tick();

    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(impl.uploads).toHaveLength(0); // no server involvement at all
    expect(btn.textContent).toBe("Saved ✓");
    expect(btn.title).toContain("downloaded Notes-on-Ganymede.md");
    window.localStorage.clear();
  });

  test("both on: one download AND one dest=saved upload", async () => {
    window.localStorage.setItem(SAVE_KEY, JSON.stringify({ server: true, device: true }));
    const impl = fetchWith({ streamParts: STREAMED });
    const { chat } = await bootChat(impl);
    const createSpy = stubObjectURL();
    await send(chat, "jupiter notes");

    lastSaveBtn().click();
    await tick();
    await tick();

    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(impl.uploads).toHaveLength(1);
    expect(lastSaveBtn().title).toContain("downloaded");
    expect(lastSaveBtn().title).toContain("data/saved/");
    window.localStorage.clear();
  });

  test("both off: new replies render no Save button", async () => {
    window.localStorage.setItem(SAVE_KEY, JSON.stringify({ server: false, device: false }));
    const { chat } = await bootChat(fetchWith({ streamParts: STREAMED }));
    await send(chat, "jupiter notes");
    expect(lastSaveBtn()).toBe(null);
    window.localStorage.clear();
  });

  test("buffered replies get the button; the welcome message never does", async () => {
    const impl = fetchWith({ buffered: true });
    const { chat } = await bootChat(impl);

    expect(document.querySelectorAll(".reply-save-btn")).toHaveLength(0); // welcome

    await send(chat, "hi");
    const btn = lastSaveBtn();
    expect(btn).toBeTruthy();
    btn.click();
    await tick();
    await tick();
    const content = await readFileText(impl.uploads[0].body.get("file"));
    expect(content).toBe("buffered reply text");
    expect(impl.uploads[0].body.get("file").name).toBe("buffered-reply-text.md");
  });

  test("a failed server save re-enables for retry; errors never get buttons", async () => {
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

    const impl2 = fetchWith({
      streamParts: [frame("done", { success: false, response: "", provider: "p", model: null, conversation_id: null, diagnostics: null, error: "provider died" })],
    });
    const { chat: chat2 } = await bootChat(impl2);
    await send(chat2, "hi");
    expect(document.querySelectorAll(".message-error .reply-save-btn")).toHaveLength(0);
  });
});
