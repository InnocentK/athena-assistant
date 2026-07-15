import { defineConfig } from "vitest/config";

// Frontend tests run in a jsdom DOM against the *shipped* static/js/*.js — no
// production refactor, no bundler. See docs/TESTING.md "Frontend tests" (M26.22).
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/js/**/*.test.js"],
    globals: false,
  },
});
