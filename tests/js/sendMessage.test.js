// tests/js/sendMessage.test.js — runtime tests for the M26.10 chat-send
// behaviours that were previously only guarded by source-structure assertions
// in the Python suite. Drives the *shipped* chat.js in jsdom with mocked fetch.

import { beforeEach, describe, expect, test, vi } from "vitest";
import { bootChat, renderedMessages, lastBubbleText } from "./loadChat.js";

// Build a fetch that answers the on-load /profile + /providers calls normally
// and routes POST /chat to `chatResponder`.
function fetchWith(chatResponder) {
  return (url, opts) => {
    if (typeof url === "string" && url.includes("/chat") && opts && opts.method === "POST") {
      return chatResponder(url, opts);
    }
    const body = url.includes("/providers") ? [] : { name: "Athena", routing: {} };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  };
}

async function send(chat, text) {
  document.getElementById("message-input").value = text;
  await chat.sendMessage();
}

describe("sendMessage — M26.10 behaviours", () => {
  test("a successful answer renders an assistant bubble and is recorded once", async () => {
    const { chat } = await bootChat(
      fetchWith(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ success: true, response: "Hello there", provider: "claude", model: "x" }),
        })
      )
    );
    await send(chat, "hi");

    const msgs = renderedMessages();
    expect(msgs).toContainEqual({ role: "user", text: "hi" });
    expect(msgs).toContainEqual({ role: "assistant", text: "Hello there" });
    // recorded in history exactly once (user + assistant)
    expect(chat.conversationHistory).toEqual([
      { role: "user", content: "hi" },
      { role: "assistant", content: "Hello there" },
    ]);
  });

  test("a provider-failure (success:false) is NOT replayed as an assistant turn", async () => {
    // The core M26.10 fix: "All providers failed." must not be pushed into
    // conversationHistory, or it gets re-sent to providers on every later turn.
    const responses = [
      { success: false, response: "All providers failed.", provider: null, model: null },
      { success: true, response: "second ok", provider: "claude", model: "x" },
    ];
    let i = 0;
    const { chat, fetchCalls } = await bootChat(
      fetchWith(() =>
        Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(responses[i++]) })
      )
    );

    await send(chat, "first");
    // rendered as an error bubble, but history holds only the user turn
    expect(renderedMessages()).toContainEqual({ role: "error", text: "All providers failed." });
    expect(chat.conversationHistory).toEqual([{ role: "user", content: "first" }]);

    await send(chat, "second");
    // the SECOND /chat request's history must not contain the failure text
    const chatPosts = fetchCalls.filter(
      (c) => typeof c.url === "string" && c.url.includes("/chat")
    );
    const sentHistory = JSON.parse(chatPosts[chatPosts.length - 1].opts.body).history;
    expect(sentHistory).toEqual([{ role: "user", content: "first" }]);
    expect(JSON.stringify(sentHistory)).not.toContain("All providers failed.");
  });

  test("a network failure shows exactly one 'Network error' and records no assistant turn", async () => {
    const { chat } = await bootChat(
      fetchWith(() => Promise.reject(new TypeError("Failed to fetch")))
    );
    await send(chat, "hi");

    const errors = renderedMessages().filter((m) => m.role === "error");
    expect(errors).toHaveLength(1);
    expect(errors[0].text).toMatch(/network error/i);
    expect(chat.conversationHistory).toEqual([{ role: "user", content: "hi" }]);
  });

  test("an HTTP error surfaces the server's detail, not a generic network error", async () => {
    const { chat } = await bootChat(
      fetchWith(() =>
        Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "Service unavailable." }) })
      )
    );
    await send(chat, "hi");

    const errors = renderedMessages().filter((m) => m.role === "error");
    expect(errors).toHaveLength(1);
    expect(errors[0].text).toBe("Service unavailable.");
    expect(errors[0].text).not.toMatch(/network error/i);
  });

  test("empty input is a no-op (no request, no bubble)", async () => {
    const { chat, fetchCalls } = await bootChat();
    const before = fetchCalls.length;
    await send(chat, "   ");
    expect(fetchCalls.filter((c) => String(c.url).includes("/chat"))).toHaveLength(0);
    expect(renderedMessages().filter((m) => m.role === "user")).toHaveLength(0);
    expect(fetchCalls.length).toBe(before);
  });
});

describe("appendMessage — XSS safety + error styling", () => {
  test("content is set as text, never parsed as HTML", async () => {
    const { chat } = await bootChat();
    chat.appendMessage("assistant", "<img src=x onerror=alert(1)>", "claude", "m");
    const bubbles = document.querySelectorAll(".message-assistant .bubble");
    const bubble = bubbles[bubbles.length - 1]; // last — skip the on-load welcome
    expect(bubble.querySelector("img")).toBeNull();       // not parsed as HTML
    expect(bubble.textContent).toBe("<img src=x onerror=alert(1)>");
  });

  test("error role gets the bubble-error class", async () => {
    const { chat } = await bootChat();
    chat.appendMessage("error", "boom", null, null);
    expect(document.querySelector(".message-error .bubble").classList.contains("bubble-error")).toBe(true);
  });
});
