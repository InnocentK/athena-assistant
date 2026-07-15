// static/js/sw.js — Athena service worker (M26.28, installable PWA).
//
// Served at /sw.js by a route in main.py that substitutes the version
// placeholder below with the running app version, so the cache name is
// release-scoped: a new release drops the previous shell cache on `activate`
// (the same anti-stale discipline as the ?v= asset versioning from M26.1).
//
// SCOPE OF CACHING — deliberately narrow (an allowlist, not a denylist):
//   * cache ONLY the static shell (CSS/JS/icons/manifest) and the root
//     navigation, via runtime caching;
//   * NEVER cache dynamic/API responses (/chat, memory, settings, DAV, backup,
//     …). Athena is server-dependent; faking offline answers would be a
//     correctness bug. Non-GET and non-shell requests bypass this worker.
//
// Registration is guarded in pwa.js: on plain HTTP (an insecure context) the
// worker never registers and the app runs as an ordinary page.

var VERSION = "__ATHENA_VERSION__";
var CACHE = "athena-shell-" + VERSION;

// Best-effort precache of the shell. Unversioned URLs here may differ from the
// page's ?v= requests; that only costs a redundant runtime fetch, never
// correctness. A single 404 must not abort install, hence the catch.
var SHELL = [
  "/",
  "/static/css/chat.css",
  "/static/js/chat.js",
  "/static/js/voice.js",
  "/static/js/pwa.js",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", function (event) {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(SHELL).catch(function () {});
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    (async function () {
      var keys = await caches.keys();
      await Promise.all(
        keys
          .filter(function (k) {
            return k.indexOf("athena-shell-") === 0 && k !== CACHE;
          })
          .map(function (k) {
            return caches.delete(k);
          })
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", function (event) {
  var req = event.request;
  var url = new URL(req.url);

  // Only same-origin GETs are eligible.
  if (req.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  var isStatic =
    url.pathname.indexOf("/static/") === 0 ||
    url.pathname === "/static/manifest.webmanifest" ||
    url.pathname === "/sw.js";
  var isNavigation = req.mode === "navigate";

  // Anything else (API/dynamic) → let the network handle it, uncached.
  if (!isStatic && !isNavigation) {
    return;
  }

  event.respondWith(
    (async function () {
      var cache = await caches.open(CACHE);
      var cached = await cache.match(req);
      if (cached) {
        // Refresh in the background so the next load is current.
        fetch(req)
          .then(function (res) {
            if (res && res.ok) {
              cache.put(req, res.clone());
            }
          })
          .catch(function () {});
        return cached;
      }
      try {
        var res = await fetch(req);
        if (res && res.ok) {
          cache.put(req, res.clone());
        }
        return res;
      } catch (err) {
        // Offline with a cold cache: for a navigation, fall back to the shell.
        if (isNavigation) {
          var shell = await cache.match("/");
          if (shell) {
            return shell;
          }
        }
        return Response.error();
      }
    })()
  );
});
