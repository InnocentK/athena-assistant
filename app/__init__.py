"""app — HTTP layer: Pydantic models (models.py) + APIRouter modules (routers/).

See docs/ARCHITECTURE.md. How routers reach app state (M26.18): each router
module does a module-level ``import main`` and references ``main.<name>`` in
its handlers; main.py ``importlib.reload``s every router as it assembles the
app, so the router's ``main`` always rebinds to the live main module (the test
suite swaps ``main`` in sys.modules per test). Never ``from main import X`` —
that captures a symbol from a stale module. Details: docs/INVARIANTS.md,
"HTTP layer / router split"."""
