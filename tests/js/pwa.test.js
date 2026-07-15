// tests/js/pwa.test.js — the PWA service-worker registration guard (M26.28).
//
// jsdom has no real service-worker runtime, so we test the *contract* that
// matters: registration is a clean no-op on an insecure context (no
// navigator.serviceWorker) and registers "/sw.js" when the API is present.
// The shipped static/js/pwa.js is loaded unmodified (same approach as the chat
// harness); a shim footer exposes registerServiceWorker.

import { afterEach, describe, expect, test, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const PWA_SRC = fs.readFileSync(
  path.join(_dir, "..", "..", "static", "js", "pwa.js"),
  "utf8"
);
const SHIM = `;window.__pwa = { registerServiceWorker };`;

function loadPwa() {
  window.eval(PWA_SRC + SHIM);
  return window.__pwa;
}

const originalNavigator = globalThis.navigator;

afterEach(() => {
  // restore whatever we monkeypatched onto navigator
  if ("serviceWorker" in navigator) {
    delete navigator.serviceWorker;
  }
  vi.restoreAllMocks();
});

describe("registerServiceWorker", () => {
  test("no-op (no throw, returns false) when serviceWorker is unavailable", () => {
    // insecure context / unsupported browser → navigator.serviceWorker absent
    expect("serviceWorker" in navigator).toBe(false);
    const { registerServiceWorker } = loadPwa();
    expect(() => registerServiceWorker()).not.toThrow();
    expect(registerServiceWorker()).toBe(false);
  });

  test("registers /sw.js when the API is present", () => {
    const register = vi.fn(() => Promise.resolve({ scope: "/" }));
    Object.defineProperty(navigator, "serviceWorker", {
      value: { register },
      configurable: true,
    });
    const { registerServiceWorker } = loadPwa();
    expect(registerServiceWorker()).toBe(true);
    expect(register).toHaveBeenCalledWith("/sw.js");
  });

  test("swallows a rejected registration (insecure origin) without throwing", () => {
    const register = vi.fn(() => Promise.reject(new Error("insecure")));
    Object.defineProperty(navigator, "serviceWorker", {
      value: { register },
      configurable: true,
    });
    const { registerServiceWorker } = loadPwa();
    // returns true (it attempted) and the rejection is caught internally
    expect(() => registerServiceWorker()).not.toThrow();
    expect(register).toHaveBeenCalled();
  });
});
