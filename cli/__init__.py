"""
cli/ — Athena command-line interface (Milestone 16).

A minimal, one-shot terminal front-end that reuses Athena's existing
provider/router/config stack. It contains no routing or provider-selection
logic of its own — it loads the active profile, builds a single-turn message,
and calls ``ProviderRouter.route(...)``, exactly the seam the HTTP ``/chat``
endpoint uses.

Run it with::

    python -m cli "What's the status of X?"
"""
