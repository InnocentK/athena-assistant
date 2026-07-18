// tests/js/loadChat.js — boot the *shipped* static/js/{voice,chat}.js inside the
// vitest jsdom DOM, unmodified. A short shim footer (appended only here, never to
// the real file) exposes the module-scope helpers so tests can drive them.
//
// This keeps production JS untouched (M26.22): the tests exercise the real code.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.join(_dir, "..", "..", "static", "js");

const VOICE_SRC = fs.readFileSync(path.join(STATIC, "voice.js"), "utf8");
const CHAT_SRC = fs.readFileSync(path.join(STATIC, "chat.js"), "utf8");

// Names hoisted to the eval's global scope that tests need handles to. Function
// declarations + top-level let/const are all in the same eval scope, so this
// footer (run in that scope) can capture them.
// One combined eval so voice.js's `var voice` and chat.js share scope (a
// separate window.eval does not reliably leak `var` to the window object in
// jsdom). The footer runs in that shared scope and re-exports what tests need.
const SHIM = `
;window.voice = voice;
;window.__chat = {
  buildDiagnosticsSummary,
  buildUsageText,
  buildTimeline,
  buildDetails,
  appendMessage,
  sendMessage,
  _splitCompleteSentences,
  _shouldSpeak,
  get conversationHistory() { return conversationHistory; },
};
`;

// Minimal DOM skeleton: every element the DOMContentLoaded handler wires up.
const SKELETON = `
  <div id="chat-window">
    <div id="messages"></div>
  </div>
  <div id="chat-status"><span class="chat-status-text"></span></div>
  <span id="status-dot"></span>
  <span id="provider-badge"></span>
  <textarea id="message-input"></textarea>
  <button id="send-btn"></button>
  <button id="ptt-btn"></button>
  <button id="memory-btn"></button>
  <button id="memory-close-btn"></button>
  <button id="settings-btn"></button>
  <button id="settings-close-btn"></button>
  <button id="history-btn"></button>
  <button id="history-close-btn"></button>
  <div id="memory-panel" class="hidden"><div id="memory-panel-body"></div></div>
  <div id="settings-panel" class="hidden"><div id="settings-panel-body"></div></div>
  <div id="history-panel" class="hidden"><div id="history-panel-body"></div></div>
`;

// Default fetch: satisfy the on-load /profile + /providers chain harmlessly.
function defaultFetch(url) {
  const body =
    typeof url === "string" && url.includes("/providers")
      ? []
      : { name: "Athena", routing: { mode: "balanced" } };
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  });
}

/**
 * Boot chat.js (and voice.js) in the current jsdom document.
 * @param {(url:string, opts?:object)=>Promise} [fetchImpl] override window.fetch
 * @returns {Promise<{chat:object, fetchCalls:Array}>}
 */
export async function bootChat(fetchImpl) {
  document.body.innerHTML = SKELETON;

  const fetchCalls = [];
  window.fetch = (url, opts) => {
    fetchCalls.push({ url, opts });
    return (fetchImpl || defaultFetch)(url, opts);
  };
  globalThis.fetch = window.fetch;

  // voice.js + chat.js + shim in ONE eval so they share a lexical scope.
  window.eval(VOICE_SRC + "\n" + CHAT_SRC + SHIM);

  // Fire DOMContentLoaded so the handler populates DOM refs + wires listeners.
  window.document.dispatchEvent(
    new window.Event("DOMContentLoaded", { bubbles: true })
  );
  // Let the on-load fetch chain (loadProfile → loadProviders) settle.
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));

  return { chat: window.__chat, fetchCalls };
}

export function messagesEl() {
  return document.getElementById("messages");
}

// All rendered bubbles, as {role, text}. role derived from the wrapper class.
export function renderedMessages() {
  return Array.from(document.querySelectorAll(".message-wrapper")).map((w) => {
    // class is "message-wrapper message-<role>" — match the role, not "wrapper".
    const role = (w.className.match(/message-(user|assistant|error)\b/) || [])[1];
    const bubble = w.querySelector(".bubble");
    return { role, text: bubble ? bubble.textContent : "" };
  });
}

// The most-recently-appended bubble for a role (skips the on-load welcome).
export function lastBubbleText(role) {
  const bubbles = document.querySelectorAll(`.message-${role} .bubble`);
  return bubbles.length ? bubbles[bubbles.length - 1].textContent : null;
}
