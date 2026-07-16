// tests/js/historyThread.test.js — M29.1: the conversation_id round-trip.
// First send posts null (server creates); the id from the response is adopted
// and sent on the next turn.

import { describe, expect, test } from "vitest";
import { bootChat } from "./loadChat.js";

function fetchWith(chatResponder) {
  return (url, opts) => {
    // M30: report the streaming endpoint unavailable so these buffered-path
    // tests keep exercising POST /chat via the fallback.
    if (typeof url === "string" && url.includes("/chat/stream")) {
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    }
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

describe("conversation_id threading (M29.1)", () => {
  test("first send posts null, later sends reuse the server's id", async () => {
    const bodies = [];
    const { chat } = await bootChat(
      fetchWith((url, opts) => {
        bodies.push(JSON.parse(opts.body));
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              success: true,
              response: "answer",
              provider: "mock",
              model: "m",
              conversation_id: "conv-abc123",
            }),
        });
      })
    );

    await send(chat, "first");
    await send(chat, "second");

    expect(bodies[0].conversation_id).toBeNull();
    expect(bodies[1].conversation_id).toBe("conv-abc123");
  });
});
