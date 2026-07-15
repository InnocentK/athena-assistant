"""
core/urlguard.py — same-origin guard for caller-supplied DAV URLs (M26.13).

The CalDAV/CardDAV endpoints accept full URLs (calendar_url, address_book_url,
hrefs) and attach the configured Basic-Auth credentials to the request. Without
a guard, a crafted URL points those credentials at an arbitrary host (SSRF +
credential exfiltration). Every caller-supplied DAV URL must therefore share
scheme+host+port with the one configured server for that integration.

Known limit (documented in docs/INVARIANTS.md): the check runs at request-build
time; HTTP redirects issued by the *configured* server are followed by the
`requests`/`caldav` stack. A malicious configured server is outside the threat
model.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


class DAVSecurityError(RuntimeError):
    """A caller-supplied URL targets a different origin than the configured
    DAV server. Mapped to HTTP 400 by the app-level exception handler."""


def _origin(url: str) -> tuple[str, str, int | None]:
    """Return (scheme, host, port) for comparison; raise on unparseable port."""
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    port = parts.port  # may raise ValueError for garbage ports
    if port is None:
        port = _DEFAULT_PORTS.get(scheme)
    return scheme, host, port


def ensure_same_origin(url: str, base: str, label: str) -> None:
    """Reject ``url`` unless it is relative or matches ``base``'s origin.

    Relative references (no scheme AND no netloc) are allowed — callers join
    them onto the configured base. Everything else must match the configured
    scheme+host+port exactly (default ports normalised, userinfo ignored on
    the hostname so ``https://trusted@evil/`` compares ``evil``).

    Raises DAVSecurityError on mismatch or unparseable URL.
    """
    parts = urlsplit(url)
    if not parts.scheme and not parts.netloc:
        return  # relative href — resolved against the configured base

    try:
        target = _origin(url)
        allowed = _origin(base)
    except ValueError as exc:
        raise DAVSecurityError(
            f"{label} URL {url!r} could not be parsed safely: {exc}"
        ) from exc

    if target != allowed:
        raise DAVSecurityError(
            f"{label} URL {url!r} does not match the configured server origin "
            f"{allowed[0]}://{allowed[1]}" + (f":{allowed[2]}" if allowed[2] else "")
            + " — refusing to send credentials to another host."
        )
