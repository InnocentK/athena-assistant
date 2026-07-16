// tests/js/usage.test.js — buildUsageText (M27.1): the web-UI token-usage line
// built from the content-free M22 trace. Loads the shipped chat.js unmodified.

import { beforeEach, describe, expect, test } from "vitest";
import { bootChat } from "./loadChat.js";

let chat;
beforeEach(async () => {
  ({ chat } = await bootChat());
});

describe("buildUsageText", () => {
  test("returns '' with no usable trace", () => {
    expect(chat.buildUsageText(null)).toBe("");
    expect(chat.buildUsageText({})).toBe("");
    expect(chat.buildUsageText({ records: [], selected: null })).toBe("");
  });

  test("formats full usage for the selected provider with thousands separators", () => {
    const out = chat.buildUsageText({
      selected: "chatgpt",
      records: [
        {
          provider: "chatgpt",
          usage: { prompt_tokens: 1204, completion_tokens: 320, total_tokens: 1524 },
        },
      ],
    });
    expect(out).toBe("Tokens: 1,204 prompt + 320 completion = 1,524 total");
  });

  test("'unavailable' when the selected record has no usage (CLI transport)", () => {
    expect(
      chat.buildUsageText({
        selected: "claude",
        records: [{ provider: "claude", usage: null }],
      })
    ).toBe("Tokens: unavailable");
  });

  test("partial counts render what's present", () => {
    expect(
      chat.buildUsageText({
        selected: "ollama",
        records: [{ provider: "ollama", usage: { total_tokens: 42 } }],
      })
    ).toBe("Tokens: 42 total");
  });
});
