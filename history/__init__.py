"""
history/ — persistent conversation history (M29.1).

Owns: append-only JSONL conversation files under
``profiles/<name>/history/``, via ``manager.ConversationStore`` (the
``manager.py`` = stateful-CRUD-over-local-files naming convention).

Does NOT own: the in-memory turn list the web UI renders from (that lives in
``static/js/chat.js``), memory extraction (``memory/``), or backups
(``backup/``). Chat content is private by design: this directory is
gitignored and never travels in portable bundles.

Tests: ``tests/test_history.py``.
"""
