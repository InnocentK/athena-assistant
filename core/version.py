"""
core/version.py — the single source of truth for Athena's release version.

Bump ONLY this constant on a code release (M26.17). Consumers:
  - main.py            → FastAPI(version=__version__)  → surfaces at /health
  - pyproject.toml     → [tool.setuptools.dynamic] version attr
  - tests/test_ops_hardening.py → asserts /health matches this value

The profile *schema* version (profiles/*/profile.yaml) is intentionally
separate and does not track releases.
"""

__version__ = "2.7.1"
