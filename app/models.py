"""
app/models.py — Pydantic request/response models for the HTTP layer (M26.18).

Moved verbatim out of main.py during the router split. Pure data models with
no dependency on app state — main.py and the app/routers/* modules both import
from here.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ChatMessageInput(BaseModel):
    role: str    # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessageInput] = []


class ChatResponse(BaseModel):
    response: str
    provider: str
    model: str | None
    success: bool
    # M24: the M22 latency trace (content-free) forwarded for the web UI's
    # text-only status/summary. None when diagnostics are disabled (M22 config).
    # M24.5 builds its richer UI from this same field — no backend change needed.
    diagnostics: dict[str, Any] | None = None


class MemoryCreateRequest(BaseModel):
    category: str
    key: str
    value: str
    notes: str = ""


class MemoryUpdateRequest(BaseModel):
    key: str | None = None
    value: str | None = None
    notes: str | None = None


class MemoryExtractRequest(BaseModel):
    user_message: str
    assistant_response: str


class SavedSearchCreate(BaseModel):
    name: str
    query: str                       # glob pattern, e.g. "*.md"
    target: str = "files"            # v1: only "files" is runnable
    path: str | None = None          # optional search root within the allowlist


class SavedSearchUpdate(BaseModel):
    name: str | None = None
    query: str | None = None
    target: str | None = None
    path: str | None = None


class SavedActionCreate(BaseModel):
    name: str
    prompt: str
    mode: str | None = None          # optional routing-mode override
    provider: str | None = None      # optional preferred-provider override


class SavedActionUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    mode: str | None = None
    provider: str | None = None


class FileAllowlistAddRequest(BaseModel):
    path: str
    label: str = ""
    search: bool = True
    read: bool = True
    write: bool = False


class FileSearchRequest(BaseModel):
    pattern: str           # glob pattern, e.g. "*.json" or "**/*.log"
    root: str | None = None  # optional sub-path within allowed roots
    # M26.3: when True, hide internal/ops artifacts (logs, audit, staging,
    # backups, *.log/.gitkeep/*.pyc) from the results. The user-facing Files
    # tab sends True by default; other callers default to the full listing.
    exclude_internal: bool = False


class FileReadRequest(BaseModel):
    path: str


class FileWriteRequest(BaseModel):
    path: str
    content: str


class TaskCreateRequest(BaseModel):
    calendar_url: str
    summary: str
    due: str | None = None        # ISO date string, e.g. "2026-06-15"
    priority: int | None = None   # 1–9 per RFC 5545; 1=highest
    description: str = ""


class StageMergeRequest(BaseModel):
    address_book_url: str
    contact_hrefs: list[str]
    merged_data: dict[str, str] = {}   # partial override: fn, email, phone, org, note


class VcfImportRequest(BaseModel):
    address_book_url: str
    vcf_content: str          # raw .vcf file content


class IcsImportRequest(BaseModel):
    calendar_url: str
    ics_content: str          # raw .ics file content


class ConflictActionRequest(BaseModel):
    action: str               # "skip" | "overwrite" | "merge_staged"
    # For "merge_staged": triggers stage_merge with incoming data
    merged_data: dict[str, str] = {}


class BackupExportRequest(BaseModel):
    include_audit: bool = False
    include_data: bool = False


class BackupRestoreRequest(BaseModel):
    zip_filename: str           # filename only, resolved against data/exports/
    confirm: bool = False       # must be True to apply
    force: bool = False         # skip version mismatch block
    diff_token: Optional[str] = None  # token obtained from GET /backup/exports/{filename}/diff


class ProfileUpdate(BaseModel):
    """
    Partial update of the editable profile settings (M26).

    Only fields explicitly present in the request body are applied. The editable
    set is intentionally narrow — the three behaviour-affecting profile fields.
    Providers, integrations, credentials, and memory are NOT editable here.
    """

    system_prompt: str | None = None
    mode: str | None = None
    preferred_provider: str | None = None
