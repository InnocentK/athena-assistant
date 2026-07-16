// tests/js/streaming.test.js — M30: sendMessage's SSE streaming path.
// Drives the shipped chat.js in jsdom with a fetch whose /chat/stream body is
// a real ReadableStream (Node 18+ global), byte-encoded SSE frames.

import { describe, expect, test } from "vitest";
import { bootChat, renderedMessages } from "./loadChat.js";

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

// fetch impl: /chat/stream answers with the given SSE parts (or a custom
// responder); /chat answers buffered; boot-time /profile + /providers normal.
function streamFetch({ streamParts, streamResponder, chatResponder } = {}) {
  return (url, opts) => {
    if (typeof url === "string" && url.includes("/chat/stream")) {
      if (streamResponder) return streamResponder(url, opts);
      return Promise.resolve({ ok: true, status: 200, body: sseStream(streamParts || []) });
    }
    if (typeof url === "string" && url.includes("/chat") && opts && opts.method === "POST") {
      if (chatResponder) return chatResponder(url, opts);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({ success: true, response: "buffered answer", provider: "claude", model: "x" }),
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

describe("sendMessage — M30 streaming", () => {
  test("chunks assemble into ONE assistant bubble; done finishes meta + history", async () => {
    const { chat, fetchCalls } = await bootChat(
      streamFetch({
        streamParts: [
          frame("chunk", { text: "Hel" }),
          frame("chunk", { text: "lo" }),
          frame("done", {
            success: true,
            response: "Hello",
            provider: "claude",
            model: "x",
            conversation_id: "conv-s1",
            diagnostics: null,
            error: null,
          }),
        ],
      })
    );
    await send(chat, "hi");

    const assistants = renderedMessages().filter((m) => m.role === "assistant" && m.text !== "");
    // welcome + exactly ONE streamed answer bubble
    const answer = assistants[assistants.length - 1];
    expect(answer.text).toBe("Hello");
    expect(assistants.filter((m) => m.text === "Hello")).toHaveLength(1);
    // provider label attached at done-time
    const label = document.querySelector(".message-assistant:last-of-type .provider-label");
    expect(label && label.textContent).toBe("claude / x");
    // recorded once
    expect(chat.conversationHistory).toEqual([
      { role: "user", content: "hi" },
      { role: "assistant", content: "Hello" },
    ]);
    // conversation id adopted → next send posts it
    await send(chat, "again");
    const posts = fetchCalls.filter((c) => String(c.url).includes("/chat/stream"));
    expect(JSON.parse(posts[posts.length - 1].opts.body).conversation_id).toBe("conv-s1");
  });

  test("a frame split across reads still assembles correctly", async () => {
    const whole =
      frame("chunk", { text: "part one, " }) +
      frame("chunk", { text: "part two" }) +
      frame("done", {
        success: true,
        response: "part one, part two",
        provider: "p",
        model: null,
        conversation_id: null,
        diagnostics: null,
        error: null,
      });
    // split mid-JSON to prove the carry-buffer works
    const cut = whole.indexOf("part two") + 3;
    const { chat } = await bootChat(
      streamFetch({ streamParts: [whole.slice(0, cut), whole.slice(cut)] })
    );
    await send(chat, "hi");

    expect(chat.conversationHistory[1]).toEqual({
      role: "assistant",
      content: "part one, part two",
    });
  });

  test("falls back to buffered /chat when the stream endpoint 404s", async () => {
    const { chat, fetchCalls } = await bootChat(
      streamFetch({
        streamResponder: () =>
          Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) }),
      })
    );
    await send(chat, "hi");

    expect(chat.conversationHistory).toEqual([
      { role: "user", content: "hi" },
      { role: "assistant", content: "buffered answer" },
    ]);
    // both endpoints were tried, in order
    const urls = fetchCalls.map((c) => String(c.url)).filter((u) => u.includes("/chat"));
    expect(urls[0]).toContain("/chat/stream");
    expect(urls[1]).not.toContain("/chat/stream");
  });

  test("falls back to buffered /chat on a network error before any chunk", async () => {
    const { chat } = await bootChat(
      streamFetch({
        streamResponder: () => Promise.reject(new TypeError("Failed to fetch")),
      })
    );
    await send(chat, "hi");

    expect(chat.conversationHistory[1]).toEqual({
      role: "assistant",
      content: "buffered answer",
    });
  });

  test("failure after chunks shows an error and never re-sends or records", async () => {
    const { chat, fetchCalls } = await bootChat(
      streamFetch({
        streamParts: [
          frame("chunk", { text: "partial " }),
          frame("done", {
            success: false,
            response: "",
            provider: "p",
            model: null,
            conversation_id: null,
            diagnostics: null,
            error: "provider died mid-stream",
          }),
        ],
      })
    );
    await send(chat, "hi");

    const errors = renderedMessages().filter((m) => m.role === "error");
    expect(errors).toHaveLength(1);
    expect(errors[0].text).toBe("provider died mid-stream");
    // M26.10: the failure is NOT an assistant turn
    expect(chat.conversationHistory).toEqual([{ role: "user", content: "hi" }]);
    // and the buffered endpoint was NOT retried (text already rendered)
    const buffered = fetchCalls.filter(
      (c) => String(c.url).endsWith("/chat") && c.opts && c.opts.method === "POST"
    );
    expect(buffered).toHaveLength(0);
  });

  test("done.response is authoritative when it differs from assembled chunks", async () => {
    const { chat } = await bootChat(
      streamFetch({
        streamParts: [
          frame("chunk", { text: "drift" }),
          frame("done", {
            success: true,
            response: "canonical text",
            provider: "p",
            model: null,
            conversation_id: null,
            diagnostics: null,
            error: null,
          }),
        ],
      })
    );
    await send(chat, "hi");

    const assistants = renderedMessages().filter((m) => m.role === "assistant");
    expect(assistants[assistants.length - 1].text).toBe("canonical text");
    expect(chat.conversationHistory[1].content).toBe("canonical text");
  });
});
