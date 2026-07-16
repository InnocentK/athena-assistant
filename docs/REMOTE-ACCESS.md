# Remote access — reaching Athena from another machine or a phone

Athena is single-user and has **no authentication layer by design**. It assumes
it is talking to its owner on a trusted, private interface — there is no login
page protecting it. That gives one hard rule, the same one stated in the
[platform matrix](PLATFORMS.md): **never expose Athena directly to an untrusted
network.** Remote reach is the operator's job, using the perimeter — exactly as
with any self-hosted server application. This page is the how-to for the two
safe patterns.

Both patterns keep Athena bound where it already is (loopback or a private
interface) and put the access control *outside* the app. Nothing here changes
Athena's code or configuration model, and no auth shim will be added to Athena
itself — if a setup seems to require one, the setup is wrong.

## Pattern A — Tailscale / VPN (recommended)

The simplest safe setup: put the machine running Athena and the devices that
should reach it on the same tailnet (or any VPN you already run).

1. Install and log in to Tailscale on the Athena host and on your phone/laptop.
2. Keep Athena bound to the private interface (the default run commands are
   fine; do not bind `0.0.0.0` on a public bridge).
3. From any device on the tailnet, open `http://<athena-host>:8000` (MagicDNS
   name or tailnet IP).

Access control is now the tailnet's job — who can reach the port is decided by
your Tailscale ACLs/device list, not by Athena.

**HTTPS on the tailnet (optional, unlocks PWA install):** service workers and
add-to-home-screen need a secure context, so plain `http://<tailnet-ip>` runs
as an ordinary browser tab ([details](PLATFORMS.md#pwa-install-requires-https)).
`tailscale serve` can front Athena with a tailnet HTTPS URL:

```bash
# on the Athena host — illustrative; check your tailscale version's syntax
tailscale serve --bg 8000
```

Then open the printed `https://<host>.<tailnet>.ts.net` URL; the browser UI is
installable as a PWA from there (M26.28). Phones follow the same pattern: join
the tailnet, open the URL, install.

## Pattern B — authenticated reverse proxy + TLS

For a LAN/home-server setup without a VPN: Athena stays on **loopback**, and a
reverse proxy terminates TLS and enforces authentication in front of it.

Illustrative Caddy config (adapt hostnames/auth to your environment — snippets
here are a starting point, not a guaranteed drop-in):

```caddy
athena.example.internal {
    basic_auth {
        # caddy hash-password to generate
        innocent $2a$14$...hashed...
    }
    reverse_proxy 127.0.0.1:8000
}
```

nginx works identically in spirit: `listen 443 ssl` + `auth_basic` (or an OIDC
module) + `proxy_pass http://127.0.0.1:8000`. The properties that matter:

- Athena itself stays bound to `127.0.0.1` — only the proxy is reachable.
- TLS terminates at the proxy (also satisfies the PWA secure-context need).
- The proxy — not Athena — authenticates every request.

## Anti-patterns (do not do these)

- Binding Athena to `0.0.0.0` on an interface that faces an untrusted network.
- Port-forwarding Athena's port directly through a router to the internet.
- "Just adding a login page" to Athena — the no-auth design is deliberate;
  access control belongs at the perimeter, where it is battle-tested.

## Verifying your setup

```bash
# What is actually listening, and on which address?
ss -tlnp | grep 8000        # Linux
lsof -iTCP:8000 -sTCP:LISTEN  # macOS
```

You want the private/loopback address there — not `0.0.0.0` (unless the host's
only network is the tailnet/LAN you trust). Then confirm the UI loads over the
chosen path from a remote device, and that the CLI still works locally. The
security trade-offs of operating a server remain yours to manage, as with any
self-hosted application — see [SECURITY.md](SECURITY.md) for what Athena does
and does not protect on its own.
