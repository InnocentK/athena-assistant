# Running Athena on <platform> — support matrix

This is the honest, single source of truth for **which platforms Athena is
supported on, to what degree, and with what caveats.** "Supported" here means
*we have run it and it works*; the other levels are stated as exactly what they
are so a future operator (or agent) doesn't over-trust an untested path. The
out-of-tree LXC installer and the remote-access guidance both reference this
page rather than restating its caveats.

Two facts shape every row below:

- Athena has **two provider transports**. *API transports* (chatgpt / grok-api /
  ollama) talk to an OpenAI-compatible endpoint using keys in `.env` — they need
  only Python and network. *CLI transports* (claude / gemini / grok / hermes)
  shell out to vendor command-line tools installed on the host, which must be
  present and logged in. Most platform caveats are really *CLI-transport*
  caveats. **Streaming (M30) is transport-dependent too:** API transports
  stream token-by-token on every platform; CLI transports answer whole (a
  subprocess's reply arrives at exit) and render buffered — expected behavior,
  not a platform fault.
- Athena is **single-user and has no auth layer** by design. It must never bind
  an untrusted network interface. Remote reach is the operator's responsibility
  (see [Remote access](#remote-access)).

## Support matrix

| Platform | Support level | What works / what to know |
|---|---|---|
| **macOS (desktop)** | **Tested** | The primary development and verification target. Both transports work: API transports with keys in `.env`, and CLI transports given the vendor CLIs are installed and logged in. This is the reference experience. |
| **Linux (desktop / server)** | **Expected good** | Same POSIX assumptions as macOS, and the CI matrix runs the full suite on Linux (Python 3.10 and 3.11), so the Python side is actively exercised on every change. CLI transports work when the vendor CLIs are present. **Recommended server platform.** |
| **Windows** | **Works with caveats** | The FastAPI backend, the browser UI, and **API transports** are expected to run under a normal CPython install. The weak point is the **CLI provider adapters**: they launch vendor CLIs as subprocesses with POSIX-flavoured assumptions (argument lists, `stdin=DEVNULL`, signal/timeout handling, path and quoting rules) and are **not tested on Windows**. If you want CLI transports on Windows, run Athena under **WSL2**, which behaves like the Linux row. Native-Windows CLI transports are unverified — treat them as unsupported until tested. |
| **Container (Docker / LXC)** | **Works — API-transport-only by default** | Python + FastAPI run trivially in a stock container. But the **vendor CLIs are not present, and they usually require interactive login**, so a headless container is **API-transport-only** (chatgpt / grok-api / ollama via keys in `.env`) unless the operator deliberately bakes the CLIs *and their authentication* into the image. Plan container deployments around API transports; treat CLI transports as an opt-in you build in yourself. |
| **Mobile (iOS / Android)** | **No native app — not a run target** | Athena is a server process; there is no mobile build and none is planned. Use Athena *from* a phone by reaching a desktop/server instance **remotely over Tailscale/VPN** and opening the existing browser UI — don't try to run the server *on* the phone. The UI is an **installable PWA** (add-to-home-screen, standalone display), but installability requires a **secure context (HTTPS)** — see the note below. |

### How to read the levels

- **Tested** — we run it; it works.
- **Expected good** — same platform assumptions as a tested one and exercised
  indirectly (e.g. Linux via CI), but not the author's daily driver.
- **Works with caveats** — part of it is fine, part of it is explicitly untested;
  the caveat says which part.
- **Not a run target** — intentionally unsupported; use the documented
  alternative instead.

## Remote access

Athena has **no built-in authentication** — it assumes it is talking to its
single owner on a trusted local interface. That assumption is load-bearing:
**do not expose Athena directly to an untrusted network.** There is no login
page to protect it.

To reach an instance from another machine or from a phone, put the access
control *outside* Athena, using either of the safe patterns:

- **Tailscale / VPN** (simplest): keep Athena bound to loopback or the private/
  tailnet interface and reach it over the VPN. Access control is the tailnet's
  job.
- **Authenticated reverse proxy + TLS**: front Athena with a proxy (Caddy /
  nginx) that terminates TLS and enforces authentication, with Athena itself
  still bound to loopback.

Either way, Athena stays bound to a private interface and never to `0.0.0.0` on
a public bridge. The security trade-offs of exposing a server are the operator's
to manage, as with any self-hosted application. **The full how-to for both
patterns (with verification steps and anti-patterns) is
[REMOTE-ACCESS.md](REMOTE-ACCESS.md)**; see [SECURITY.md](SECURITY.md) for what
Athena does and does not protect.

### PWA install requires HTTPS

The browser UI can be **installed as a PWA** (M26.28) — an app icon, a
standalone window, faster loads. But service workers and "add to home screen"
only work in a **secure context**: HTTPS, or `localhost`/`127.0.0.1`. Reaching
the server by bare `http://<tailscale-ip>:8000` is *not* a secure context, so
the install option simply won't appear and the page runs as an ordinary tab (no
error). To get installability over a tailnet, terminate TLS — `tailscale serve`
(gives an HTTPS tailnet URL) or the reverse-proxy-plus-TLS pattern above. In
other words, the PWA is polish layered on the same remote-access setup, not a
way around it.

### Voice / conversation mode is browser- and transport-dependent (M31.0)

The voice features (M30.6 controls, M31.0 conversation mode) ride the
browser's **Web Speech API**, so support follows the *browser*, not the OS:
speech *output* (TTS) works in all modern browsers, but speech *input* (the
mic button, and therefore the hands-free loop) is **Chromium/Safari only** —
Firefox ships no usable SpeechRecognition. The mic additionally requires a
**secure context** (same rule as the PWA above: HTTPS or localhost), so over
a tailnet you need `tailscale serve`/TLS before the mic button will work.
Two more honest limits: **CLI-transport providers answer whole**, so their
"streaming speech" is one utterance after the wait — the live feel needs an
API transport (chatgpt / grok-api / ollama); and replies are spoken **as
written** (markdown syntax and code blocks included). Headphones are
recommended in conversation mode — the mic never opens while Athena is
speaking, but speaker echo into an open mic is physically possible. On
narrow/mobile layouts (<600px) the mic button is hidden, so conversation
mode is a desktop-browser feature today.

## See also

- [INSTALLATION.md](INSTALLATION.md) — installing and running (local or Docker).
- [SECURITY.md](SECURITY.md) — Athena's security model and boundaries.
- [CONFIGURATION.md](CONFIGURATION.md) — providers, transports, and integrations.
