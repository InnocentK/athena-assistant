// tests/js/diagnostics.test.js — pure-logic tests for buildDiagnosticsSummary
// (the content-free M22 trace → one-line summary). No DOM bootstrap needed.

import { beforeEach, describe, expect, test } from "vitest";
import { bootChat } from "./loadChat.js";

let chat;
beforeEach(async () => {
  ({ chat } = await bootChat());
});

describe("buildDiagnosticsSummary", () => {
  test("returns '' for missing/malformed diagnostics", () => {
    expect(chat.buildDiagnosticsSummary(null)).toBe("");
    expect(chat.buildDiagnosticsSummary({})).toBe("");
    expect(chat.buildDiagnosticsSummary({ records: "nope" })).toBe("");
  });

  test("no selected provider → 'No provider answered.'", () => {
    expect(
      chat.buildDiagnosticsSummary({ records: [], selected: null })
    ).toBe("No provider answered.");
  });

  test("clean single-provider answer, capitalised, with timing", () => {
    const out = chat.buildDiagnosticsSummary({
      selected: "claude",
      total_ms: 1500,
      records: [{ provider: "claude", transport: "cli", outcome: "ok" }],
    });
    expect(out).toBe("Answered via claude/cli in 1.5s.");
  });

  test("prior failed attempts are listed before the winning provider", () => {
    const out = chat.buildDiagnosticsSummary({
      selected: "gemini",
      total_ms: 800,
      records: [
        { provider: "claude", transport: "cli", outcome: "timeout" },
        { provider: "gemini", transport: "cli", outcome: "ok" },
      ],
    });
    expect(out).toContain("claude/cli timeout");
    expect(out).toContain("answered via gemini/cli in 0.8s.");
  });
});
