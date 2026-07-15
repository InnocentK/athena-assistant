// static/js/pwa.js — register the service worker for the installable PWA
// (M26.28). Loaded from index.html.
//
// GRACEFUL DEGRADATION IS THE CONTRACT: service workers require a secure
// context (HTTPS, or localhost/127.0.0.1). Over a plain http://<ip>:port origin
// — e.g. reaching the server by bare Tailscale IP without TLS —
// `navigator.serviceWorker` is undefined, so this is a clean no-op and the page
// keeps working as an ordinary browser tab. Registration errors are swallowed
// for the same reason: the PWA is polish, never a hard dependency.

function registerServiceWorker() {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
    return false;
  }
  try {
    var reg = navigator.serviceWorker.register("/sw.js");
    if (reg && typeof reg.catch === "function") {
      reg.catch(function () {
        // insecure origin / transient failure — ignore.
      });
    }
    return true;
  } catch (e) {
    return false;
  }
}

if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("load", registerServiceWorker);
}
