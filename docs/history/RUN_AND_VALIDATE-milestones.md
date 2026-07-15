# Athena Assistant — Run and Validate

Practical guide for setting up, running, and validating each milestone.

---

## 1. Setup

```bash
# Clone and enter
git clone <your-repo-url> athena-assistant
cd athena-assistant

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment file
cp .env.example .env
# Edit .env — minimum required for Milestone 1 and 2:
#   APP_ENV=development
#   ACTIVE_PROFILE=athena
#   OPENAI_API_KEY=sk-...        # Required only for ChatGPT adapter
```

### Optional: Taskfile shortcuts

If `task` is installed (https://taskfile.dev):

```bash
task setup          # first-time setup (venv + deps + .env)
task run            # start dev server (equivalent to bash run.sh)
task test:run       # run all tests (equivalent to pytest)
task up             # start Docker stack
task --list         # discover all tasks
```

---

## 2. Run

### Local (uvicorn)

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Docker

```bash
docker compose up --build
```

The API is available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

---

## 3. Validate Milestone 1

### Health check

```bash
curl http://localhost:8000/health
```

Expected:
```json
{"status": "ok", "profile": "Athena", "version": "0.2.0"}
```

### Profile config

```bash
curl http://localhost:8000/profile
```

Expected: full contents of `profiles/athena/profile.yaml` as JSON, including
`name`, `description`, `system_prompt`, `routing`, `memory`, etc.

---

## 4. Validate Milestone 2

### List providers

```bash
curl http://localhost:8000/providers
```

Expected shape (values depend on your environment):
```json
[
  {"name": "claude",      "enabled": true,  "available": false, "cost_tier": "high",   "type": "cli"},
  {"name": "gemini",      "enabled": true,  "available": false, "cost_tier": "medium", "type": "cli"},
  {"name": "grok",        "enabled": true,  "available": false, "cost_tier": "low",    "type": "cli"},
  {"name": "chatgpt",     "enabled": true,  "available": true,  "cost_tier": "medium", "type": "api"},
  {"name": "hermes",      "enabled": false, "available": false, "cost_tier": "low",    "type": "stub"},
  {"name": "chatgpt_cli", "enabled": false, "available": false, "cost_tier": "medium", "type": "stub"}
]
```

`available: true` for `chatgpt` requires `OPENAI_API_KEY` to be set.  
`available: true` for CLI adapters requires the respective binary on PATH.

### Send a chat message

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2 + 2?", "history": []}' | python3 -m json.tool
```

Expected shape on success:
```json
{
  "response": "4.",
  "provider": "gemini",
  "model": null,
  "success": true
}
```

The `provider` field shows which adapter actually answered.

### Send a message with conversation history

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "And what is that squared?",
    "history": [
      {"role": "user",      "content": "What is 2 + 2?"},
      {"role": "assistant", "content": "4."}
    ]
  }' | python3 -m json.tool
```

### When providers are unavailable (expected behaviour)

If no CLI tools are installed and `OPENAI_API_KEY` is not set, the router will
exhaust all providers and return:

```json
{
  "response": "All providers failed.",
  "provider": "none",
  "model": null,
  "success": false
}
```

This is expected — it is not a bug. Install the required CLI or set the API key
to get a successful response.

### Checking router logs

Provider routing decisions are written to `logs/app.log`. Look for lines tagged
`Router:`:

```
2025-01-01 12:00:00  INFO      athena  Router: mode=balanced preferred=none attempt_order=['gemini', 'claude', 'chatgpt', 'grok']
2025-01-01 12:00:00  INFO      athena  Router: attempting provider 'gemini' (mode=balanced).
2025-01-01 12:00:01  INFO      athena  Router: provider 'gemini' succeeded (model=n/a).
```

---

## 5. Validate Milestone 3

Open http://localhost:8000 in a browser.

Expected:
- Dark-themed chat UI loads
- Header shows the assistant name and a provider badge
- A welcome message appears in the chat window
- Type a message and press Enter (or click Send)
- If a provider is available: a response appears with the provider name shown below it
- If no provider is available: an error-style message appears with "All providers failed."
- The provider badge in the header updates after each response
- Shift+Enter inserts a newline without sending

Manual checks:
- Resize the window to < 600px wide — layout should remain usable
- Send several messages — conversation history should be maintained (assistant remembers prior turns within the session)
- Refresh the page — history is cleared (expected; persistence is Milestone 4)

---

## 6. Validate Milestone 4

### Memory API

```bash
# List all memories
curl http://localhost:8000/memory

# List pending review queue
curl http://localhost:8000/memory/pending

# Add a memory manually
curl -s -X POST http://localhost:8000/memory \
  -H "Content-Type: application/json" \
  -d '{"category": "preferences", "key": "date_format", "value": "ISO 8601"}' | python3 -m json.tool

# Trigger auto-extraction
curl -s -X POST http://localhost:8000/memory/extract \
  -H "Content-Type: application/json" \
  -d '{"user_message": "I prefer ISO dates", "assistant_response": "Noted."}' | python3 -m json.tool

# Check pending after extraction
curl http://localhost:8000/memory/pending

# Approve a pending memory (replace <id> with the id from the above response)
curl -s -X POST http://localhost:8000/memory/pending/<id>/approve | python3 -m json.tool
```

### Memory UI

Open http://localhost:8000, click the **Memory** button in the header.

- **Review queue** tab: shows pending memories with Approve/Discard buttons
- **All memories** tab: shows saved memories organised by category with Delete buttons
- After approving a pending entry, switch to **All memories** to confirm it moved

---

## 7. Validate Milestone 5

### Voice input (browser)
1. Open http://localhost:8000 in Chrome or Edge
2. The microphone button (🎤) in the input area should be enabled (not greyed out)
3. Click the button — browser will prompt for microphone permission on first use
4. Allow microphone access
5. Speak a message — the button turns red while listening
6. When you stop speaking, the transcript appears in the text field and sends automatically
7. The assistant response is read aloud via the browser's speech synthesis

### If the button is greyed out / disabled
The browser does not support the Web Speech API. This is expected in Firefox and Safari.
Use Chrome or Edge for voice input. The text input continues to work in all browsers.

### Voice stub endpoints
```bash
curl -s -X POST http://localhost:8000/voice/transcribe   # returns 501 — expected
curl -s -X POST http://localhost:8000/voice/synthesize   # returns 501 — expected
```
Both return 501 with a message explaining the local upgrade path.

### Local voice upgrade path
See `voice/stubs.py` for step-by-step instructions to replace the browser fallback with:
- `faster-whisper` for local CPU-based STT
- `piper-tts` for local CPU-based TTS

---

## 8. Environment variables

| Variable        | Required for          | Milestone |
|-----------------|-----------------------|-----------|
| `APP_ENV`       | All environments      | M1        |
| `ACTIVE_PROFILE`| Profile selection     | M1        |
| `LOG_LEVEL`     | Log verbosity (opt.)  | M1        |
| `OPENAI_API_KEY`| ChatGPT API adapter   | M2        |

CLI adapters (Claude, Gemini, Grok) do not use env vars — they require the
corresponding binary to be installed and authenticated on the host system.

---

## 9. Bug fixed — Milestone 3 hotfix

**Root cause:** `Jinja2Templates.TemplateResponse()` signature changed in Starlette >= 0.28.
The generated code used the old two-argument form `TemplateResponse("index.html", context_dict)`,
which passes the dict as the template name — an unhashable type — causing a 500 on every `GET /`.

**Fix (one line in `main.py`):**
```python
# Before (broken on Starlette >= 0.28 / installed version 1.2.1)
_templates.TemplateResponse("index.html", {"request": request, "assistant_name": assistant_name})

# After (correct for current Starlette)
_templates.TemplateResponse(request, "index.html", {"assistant_name": assistant_name})
```
`request` moves to the first positional argument and is no longer included in the context dict.

---

## 9. Validate Milestone 6

### File allowlist and file I/O

```bash
# List allowlist
curl http://localhost:8000/files/allowlist

# Add an entry
curl -s -X POST http://localhost:8000/files/allowlist \
  -H "Content-Type: application/json" \
  -d '{"path":"data","label":"test","search":true,"read":true,"write":true}'

# Search for files
curl -s -X POST http://localhost:8000/files/search \
  -H "Content-Type: application/json" \
  -d '{"pattern":"**/*.yaml"}'

# Read a file (use a file known to exist under data/ or logs/)
curl -s "http://localhost:8000/files/read?path=data/.gitkeep"

# Write a file
curl -s -X POST http://localhost:8000/files/write \
  -H "Content-Type: application/json" \
  -d '{"path":"data/test.txt","content":"hello from milestone 6"}'

# Reload allowlist config
curl -s -X PATCH http://localhost:8000/files/allowlist/reload

# Check audit log was written
ls audit/
cat audit/*file_audit.log
```

Expected: all 200 responses, audit log created after write.

---

## 10. Validate Milestone 7 (CalDAV)

Real CalDAV credentials are not required to validate Milestone 7. All checks below work with CalDAV **disabled** (the default).

### 1. Server starts at version 0.7.0

```bash
curl http://localhost:8000/health
```

Expected:
```json
{"status": "ok", "profile": "Athena", "version": "0.7.0"}
```

### 2. Startup log shows CalDAV disabled (not an error)

Check `logs/app.log` or server output for:
```
CalDAV integration disabled (config/caldav.yaml enabled: false).
```
This confirms the disabled path is clean — no exception or traceback.

### 3. All four CalDAV endpoints return 503 when disabled

```bash
# Calendars
curl -s http://localhost:8000/caldav/calendars

# Events
curl -s "http://localhost:8000/caldav/events?calendar_url=https://dav.mailbox.org/test"

# Tasks (list)
curl -s "http://localhost:8000/caldav/tasks?calendar_url=https://dav.mailbox.org/test"

# Tasks (create)
curl -s -X POST http://localhost:8000/caldav/tasks \
  -H "Content-Type: application/json" \
  -d '{"calendar_url":"https://dav.mailbox.org/test","summary":"test task"}'
```

All four should return HTTP **503** with:
```json
{"detail": "CalDAV integration not available. Set CALDAV_URL/USERNAME/PASSWORD and enabled: true in config/caldav.yaml."}
```

### 4. How to enable CalDAV

1. Add to your `.env`:
   ```
   CALDAV_URL=https://dav.mailbox.org
   CALDAV_USERNAME=you@mailbox.org
   CALDAV_PASSWORD=your_app_password
   ```
2. Set `enabled: true` in `config/caldav.yaml`.
3. Restart the server.

### 5. `POST /caldav/tasks` body schema

| Field          | Type    | Required | Description                                    |
|----------------|---------|----------|------------------------------------------------|
| `calendar_url` | string  | Yes      | CalDAV calendar URL                            |
| `summary`      | string  | Yes      | Task title                                     |
| `due`          | string  | No       | ISO date string, e.g. `"2026-06-15"`           |
| `priority`     | integer | No       | RFC 5545 priority 1–9; 1 = highest             |
| `description`  | string  | No       | Free-text description (default empty string)   |

Example:
```json
{
  "calendar_url": "https://dav.mailbox.org/calendars/you@mailbox.org/tasks/",
  "summary": "Review Athena Milestone 7",
  "due": "2026-06-15",
  "priority": 1,
  "description": "Verify all curl checks pass"
}
```

---

## 11. Known limitations (current)

- **Conversation history is session-only.** Chat history is maintained in the browser
  session and is lost on page refresh. Memory entries (preferences, facts, etc.) are
  persisted to YAML files via the Milestone 4 memory system.
- **Memory auto-extraction uses pattern matching only.** LLM-assisted extraction is
  not active in Milestone 4. Only explicit preference and environment signals matching
  the built-in regex patterns are detected; all candidates go to pending_review first.
- **No web search.** Tool calls and search integrations are not wired yet.
- **Voice uses browser APIs (Milestone 5).** STT uses the Web Speech API (Chrome/Edge only);
  TTS uses SpeechSynthesis (all modern browsers). Local CPU-based replacements
  (faster-whisper for STT, piper-tts for TTS) are documented in `voice/stubs.py` and
  the stub endpoints `/voice/transcribe` and `/voice/synthesize` (both return 501 until
  the local upgrade is applied).
- **No file access.** File read/write tools are added in Milestone 6.
- **No DAV/IMAP integration.** Mailbox, calendar, and Nextcloud integrations are
  Milestones 7–9.
- **CLI adapters require installed binaries.** Claude, Gemini, and Grok adapters
  call `claude -p`, `gemini -p`, and `grok -p` respectively. The CLI tools must
  be installed, on PATH, and authenticated before these adapters become available.
- **ChatGPT adapter requires `OPENAI_API_KEY`.** Without the env var set,
  `available` will be `false` and the adapter is skipped in routing.
- **Hermes and ChatGPT CLI are stubs.** They always return `available: false`
  and are never used for routing. See their source files for implementation notes.

---

## 12. Milestone 8 — CardDAV Contacts validation

Milestone 8 adds CardDAV contacts integration with a **safe merge workflow**.
Duplicate detection runs automatically and locally; write-back (commit merge, delete contact)
requires explicit human API calls.

### Quick smoke test (CardDAV disabled — 503 expected for all)

When `config/carddav.yaml` has `enabled: false` (the default), all CardDAV endpoints
return HTTP 503 with a descriptive error message.

```bash
# List address books → 503
curl -s http://localhost:8000/carddav/addressbooks

# List contacts → 503
curl -s "http://localhost:8000/carddav/contacts?address_book_url=https://dav.mailbox.org/test"

# Search contacts → 503
curl -s "http://localhost:8000/carddav/contacts/search?address_book_url=test&q=john"

# Detect duplicates → 503
curl -s "http://localhost:8000/carddav/duplicates?address_book_url=test"

# Stage a merge → 503
curl -s -X POST http://localhost:8000/carddav/merges \
  -H "Content-Type: application/json" \
  -d '{"address_book_url":"test","contact_hrefs":["/a","/b"],"merged_data":{}}'

# List staged merges → 503
curl -s http://localhost:8000/carddav/merges

# Get staged merge → 503
curl -s http://localhost:8000/carddav/merges/nonexistent

# Commit staged merge → 503
curl -s -X POST http://localhost:8000/carddav/merges/nonexistent/commit

# Discard staged merge → 503
curl -s -X DELETE http://localhost:8000/carddav/merges/nonexistent

# Delete a contact → 503
curl -s -X DELETE "http://localhost:8000/carddav/contacts?address_book_url=test&href=/test.vcf"
```

All responses should include the detail message:
`"CardDAV integration not available. Set CARDDAV_URL/USERNAME/PASSWORD and enabled: true in config/carddav.yaml."`

### Enabling CardDAV

1. Add credentials to `.env`:
   ```
   CARDDAV_URL=https://dav.mailbox.org
   CARDDAV_USERNAME=you@mailbox.org
   CARDDAV_PASSWORD=your_app_password
   ```
   (For Mailbox.org these are the same as CalDAV credentials.)

2. Set `enabled: true` in `config/carddav.yaml`.

3. Restart the server. The startup log confirms: `CardDAVClient initialised successfully.`

### Safety rule for merge commit

Duplicate detection (`GET /carddav/duplicates`) and merge staging (`POST /carddav/merges`)
are always read-only with respect to the server. The staged merge JSON file is stored
locally in `data/carddav_staged/`.

**Commit write-back** (`POST /carddav/merges/{id}/commit`) writes to the server and deletes
source contacts. This endpoint must **only** be called by an explicit human decision —
never automatically or as a side-effect of another operation.

### `POST /carddav/merges` body schema

| Field              | Type          | Required | Description                                      |
|--------------------|---------------|----------|--------------------------------------------------|
| `address_book_url` | string        | Yes      | CardDAV address book URL                         |
| `contact_hrefs`    | list[string]  | Yes      | 2+ hrefs of contacts to merge                    |
| `merged_data`      | dict          | No       | Override fields: fn, email, phone, org, note     |

Example:
```json
{
  "address_book_url": "https://dav.mailbox.org/carddav/you@mailbox.org/contacts/",
  "contact_hrefs": [
    "/carddav/you@mailbox.org/contacts/abc123.vcf",
    "/carddav/you@mailbox.org/contacts/def456.vcf"
  ],
  "merged_data": {
    "fn": "Jane Smith",
    "email": "jane@example.com"
  }
}
```

### Staged merge lifecycle

```
POST /carddav/merges         → status: "pending"   (local file written, no server write)
GET  /carddav/merges         → list all staged merges
GET  /carddav/merges/{id}    → full record including merged_vcard string
POST /carddav/merges/{id}/commit  → status: "committed"  (server write + source deletes)
DELETE /carddav/merges/{id}  → status: "discarded"  (local update, no server write)
```

---

## Milestone 9 — Nextcloud Read-Only Integration

All Nextcloud operations are read-only. Enable via `config/nextcloud.yaml` and `.env`.

### Quick smoke test (Nextcloud disabled — 503 expected)

When `config/nextcloud.yaml` has `enabled: false` (the default), all Nextcloud endpoints
return HTTP 503 with a descriptive error message.

```bash
# Health check → 200, version 0.9.0
curl -s http://localhost:8000/health

# Nextcloud ping → 503
curl -s http://localhost:8000/nextcloud/ping

# Nextcloud user → 503
curl -s http://localhost:8000/nextcloud/user

# List files → 503
curl -s "http://localhost:8000/nextcloud/files?path=/"

# Read file → 503
curl -s "http://localhost:8000/nextcloud/files/read?path=/test.txt"

# Search files → 503
curl -s "http://localhost:8000/nextcloud/files/search?query=readme"

# List notes → 503
curl -s http://localhost:8000/nextcloud/notes

# Get note → 503
curl -s http://localhost:8000/nextcloud/notes/1

# Recent activity → 503
curl -s "http://localhost:8000/nextcloud/activity?limit=10"
```

Expected: all Nextcloud endpoints return HTTP 503. `/health` returns 200 with `"version":"0.9.0"`.

### Enabling Nextcloud

1. Add credentials to `.env`:
   ```
   NEXTCLOUD_URL=https://cloud.example.com
   NEXTCLOUD_USERNAME=your_username
   NEXTCLOUD_PASSWORD=your_app_password
   ```
   The base URL is configurable — use a Proxmox LAN IP or a public domain.

2. Set `enabled: true` in `config/nextcloud.yaml`.

3. Restart the server. The startup log confirms: `NextcloudClient initialised successfully.`

### Notes on optional apps

- `GET /nextcloud/notes` requires the Nextcloud Notes app. Returns `[]` if not installed.
- `GET /nextcloud/activity` requires the Nextcloud Activity app. Returns `[]` if not installed.
- `GET /nextcloud/files/search` uses DASL SEARCH; falls back to local name filtering if the server does not support it.

### Safety note

All Nextcloud endpoints are read-only. The client performs no uploads, modifications, or deletes against the Nextcloud server.

---

## 12. Milestone 10 — Final Checks

### Version check
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","profile":"Athena","version":"1.0.0"}
```

### Docker build check
```bash
docker compose build 2>&1 | tail -5
# Expected: build succeeds, no errors
```

### .dockerignore check
```bash
# Verify .dockerignore exists
ls -la .dockerignore
```

### Documentation check
```bash
ls docs/
# Expected: ARCHITECTURE.md  HANDOFF.md  RUNBOOK.md  RUN_AND_VALIDATE.md
```

### Startup with named volumes (Docker)
```bash
docker compose up -d
sleep 5
curl http://localhost:8000/health
docker compose down
```

---

## 13. Milestone 11 — Run the test suite

```bash
source .venv/bin/activate
pytest
```

Expected: all tests pass. No live credentials or network access required.

To see verbose output:
```bash
pytest -v --tb=short
```

See `docs/TESTING.md` for full coverage details.

---

## 14. Milestone 12 — VCF/ICS Import & Export

### CardDAV import (requires CardDAV enabled in config/carddav.yaml)
```bash
curl -s -X POST http://localhost:8000/carddav/import \
  -H "Content-Type: application/json" \
  -d '{"address_book_url":"https://dav.mailbox.org/carddav/","vcf_content":"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Test Person\r\nEND:VCARD"}'
# Returns ImportSummary: {batch_id, total, imported, skipped_conflicts, invalid, failed, conflict_ids, errors}
```

### CalDAV import (requires CalDAV enabled in config/caldav.yaml)
```bash
curl -s -X POST http://localhost:8000/caldav/import \
  -H "Content-Type: application/json" \
  -d '{"calendar_url":"https://dav.mailbox.org/caldav/","ics_content":"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:test-uid\r\nSUMMARY:Test\r\nDTSTART:20260601T100000Z\r\nDTEND:20260601T110000Z\r\nEND:VEVENT\r\nEND:VCALENDAR"}'
```

### List conflict queues (no auth required — reads local files)
```bash
curl -s http://localhost:8000/carddav/conflicts
curl -s http://localhost:8000/caldav/conflicts
# Both return [] when no conflicts exist
```

### Resolve a conflict (example: skip)
```bash
# Replace <batch_id> and <conflict_id> from the conflict queue response
curl -s -X POST http://localhost:8000/carddav/conflicts/<batch_id>/<conflict_id>/resolve \
  -H "Content-Type: application/json" \
  -d '{"action":"skip"}'
```

### CardDAV export (requires CardDAV enabled)
```bash
curl -s "http://localhost:8000/carddav/export?address_book_url=https://dav.mailbox.org/carddav/" \
  -o contacts.vcf
```

### CalDAV export (requires CalDAV enabled)
```bash
curl -s "http://localhost:8000/caldav/export?calendar_url=https://dav.mailbox.org/caldav/" \
  -o calendar.ics
```

### Run the full test suite (includes Milestone 12 tests)
```bash
source .venv/bin/activate
pytest tests/test_dav_io.py -v
pytest -v  # all tests
```

---

## 14. Milestone 11.5 — Taskfile validation

```bash
# Verify Taskfiles exist
ls Taskfile.yml tests/Taskfile.yml

# If task CLI is installed:
task --list

# Confirm tests still pass (task wraps pytest)
task test:run
# OR without task:
pytest
```

---

## 15. Milestone 13 — Backup/Export/Import validation

### Create a backup
```bash
curl -s -X POST http://localhost:8000/backup/exports \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

### List backups
```bash
curl -s http://localhost:8000/backup/exports | python3 -m json.tool
```

### Inspect a backup (replace <filename> with the name returned above)
```bash
curl -s http://localhost:8000/backup/exports/<filename>/inspect | python3 -m json.tool
```

### Dry-run diff (no writes)
```bash
curl -s http://localhost:8000/backup/exports/<filename>/diff | python3 -m json.tool
```

### Restore (dry-run, confirm=false)
```bash
curl -s -X POST http://localhost:8000/backup/restore \
  -H "Content-Type: application/json" \
  -d '{"zip_filename":"<filename>","confirm":false}' | python3 -m json.tool
```

### Restore (apply, confirm=true)
```bash
curl -s -X POST http://localhost:8000/backup/restore \
  -H "Content-Type: application/json" \
  -d '{"zip_filename":"<filename>","confirm":true}' | python3 -m json.tool
```

### Download a backup zip
```bash
curl -OJ http://localhost:8000/backup/exports/<filename>
```

### Delete a backup
```bash
curl -s -X DELETE http://localhost:8000/backup/exports/<filename> | python3 -m json.tool
```

### Taskfile shortcuts
```bash
task backup        # create a backup (profiles + config)
task backup:list   # list available backups
```

### Run Milestone 13 tests
```bash
source .venv/bin/activate
pytest tests/test_backup.py -v
pytest -v  # all tests
```


---

## Milestone 14 — DAV Sync Status

### DAV status overview (always 200, even when disabled)
```bash
curl -s http://localhost:8000/status/dav | python3 -m json.tool
```

### Single integration status
```bash
curl -s http://localhost:8000/status/dav/caldav
curl -s http://localhost:8000/status/dav/carddav
curl -s http://localhost:8000/status/dav/nextcloud
```

### On-demand connection check (requires integration enabled)
```bash
curl -s -X POST http://localhost:8000/status/dav/caldav/check
curl -s -X POST http://localhost:8000/status/dav/carddav/check
curl -s -X POST http://localhost:8000/status/dav/nextcloud/check
```

Expected when all integrations disabled:
- `GET /status/dav` returns 200 with all `enabled: false`
- `POST /status/dav/{integration}/check` returns 503

### Run Milestone 14 tests
```bash
source .venv/bin/activate
pytest tests/test_dav_status.py -v
pytest -v  # all tests
```

## Milestone 15 — Operational Hardening

### Health check — confirms version 2.6.10
```bash
curl -s http://localhost:8000/health
# Expected: {"status":"ok","profile":"Athena","version":"2.6.10"}
```

### Restore token flow (diff_token safety)

Step 1: Create a backup
```bash
curl -s -X POST http://localhost:8000/backup/exports \
  -H 'Content-Type: application/json' \
  -d '{"include_audit":false,"include_data":false}' | python3 -m json.tool
# Note the "filename" field
```

Step 2: Get a diff — returns diff_token
```bash
FILENAME="<filename from step 1>"
curl -s "http://localhost:8000/backup/exports/${FILENAME}/diff" | python3 -m json.tool
# Note the "diff_token" field
```

Step 3: Restore without token — expect 409
```bash
curl -s -X POST http://localhost:8000/backup/restore \
  -H 'Content-Type: application/json' \
  -d "{\"zip_filename\":\"${FILENAME}\",\"confirm\":true}"
# Expected: 409 with diff_token required message
```

Step 4: Restore with valid token — expect 200
```bash
TOKEN="<diff_token from step 2>"
curl -s -X POST http://localhost:8000/backup/restore \
  -H 'Content-Type: application/json' \
  -d "{\"zip_filename\":\"${FILENAME}\",\"confirm\":true,\"diff_token\":\"${TOKEN}\"}" \
  | python3 -m json.tool
# Expected: {"restored": true, ...}
```

Or use the Taskfile shortcut:
```bash
task restore:diff ZIP=<filename>
```

### Ops audit log
```bash
task ops:audit
# Shows last 40 lines of today's ops audit log
# Or directly:
cat audit/*_ops_audit.log
```

Audit events written by the server:
- `restore_confirm` — on POST /backup/restore with confirm=True
- `commit_merge` — on POST /carddav/merges/{id}/commit
- `memory_delete` — on DELETE /memory/{id}
- `file_write` — on POST /files/write

### Asyncio timeout behaviour
Blocking operations return HTTP 504 if they exceed their timeout:
- POST /backup/restore → 60s
- POST /status/dav/{integration}/check → 30s
- POST /carddav/import → 30s
- POST /caldav/import → 30s
- POST /carddav/merges/{id}/commit → 30s

### Run Milestone 15 tests
```bash
source .venv/bin/activate
pytest tests/test_ops_hardening.py -v
pytest -v  # all tests (196 passing)
```

---

## 16. Validate Milestone 15.5 — Ollama (local model)

Ollama is **disabled by default**. These steps assume a running Ollama instance.

### Enable and configure

1. Pull a model and confirm it is available:
   ```bash
   ollama pull gemma4        # or: ollama pull qwen3.6
   ollama list
   ```

2. Set env vars in `.env`:
   ```
   OLLAMA_API_URL=http://localhost:11434/v1   # or a remote host, e.g. http://192.168.1.20:11434/v1
   OLLAMA_MODEL=gemma4
   # OLLAMA_TIMEOUT=120                        # optional, seconds (default 120)
   ```
   No API key is needed — Ollama ignores authentication and a dummy key is supplied automatically.

3. Enable the adapter in `config/providers.yaml`:
   ```yaml
   adapters:
     ollama:
       enabled: true
   ```

4. Restart the server.

### Confirm availability

```bash
curl -s http://localhost:8000/providers | python3 -m json.tool
```
Look for the `ollama` entry with `"enabled": true` and `"available": true`. If Ollama is
unreachable or `OLLAMA_MODEL` is unset, `available` is `false` (a ~1s health check) and the
router silently skips it and falls back to the next provider.

### Route to Ollama

Force it via the active profile:
```yaml
# profiles/athena/profile.yaml
routing:
  preferred_provider: ollama
```
…or select budget-first (Ollama leads that tier):
```yaml
routing:
  mode: budget-first
```

Then send a chat and confirm the response's `provider` field is `ollama`:
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Say hello in one word."}' | python3 -m json.tool
```

### Switching models

Change `OLLAMA_MODEL` (e.g. from `gemma4` to `qwen3.6`) and restart. Only one model is
active per running configuration; there is no automatic multi-model selection in this milestone.

### Run Milestone 15.5 tests

```bash
source .venv/bin/activate
pytest tests/test_provider_ollama.py -v
pytest tests/test_provider_router.py -v
```
All Ollama tests are fully mocked — no running Ollama instance is required.

---

## 18. Validate the CLI and the `athena` command (Milestones 16–17)

The CLI reuses the same provider/router/profile stack as the server, with no server running.

### Install the `athena` command (one-time)

```bash
pip install -r requirements.txt
pip install -e .
athena --help
```
`python -m cli ...` works without installing and is equivalent to `athena ...` everywhere below.

### One-shot prompt (happy path)

```bash
athena "What is 2 + 2?"
echo $?                         # 0 on success
athena ask "What is 2 + 2?"     # the ask alias is equivalent
```
The answer prints to stdout; with at least one provider available the exit code is 0.

### Provider availability

```bash
athena --list-providers
```
Prints a table (name, enabled, available, cost, type) and exits 0 — no prompt needed.

### Overrides

```bash
athena --provider ollama "Summarise my notes"   # force preferred_provider
athena --mode budget-first "Quick answer"        # routing mode for this run
athena --profile work "What's on my plate?"      # different profile
athena --no-memory "One-off question"            # skip auto-extraction
```

### Error cases (note the exit codes)

```bash
athena                       # missing prompt     → usage error, exit 2
athena ask                   # ask with no prompt → usage error, exit 2
athena --profile nope "hi"   # invalid profile    → error on stderr, exit 1
# With no providers available, an answer attempt prints an error to stderr and exits 1.
```

stdout carries only the answer; logs and errors go to stderr, so `athena "..." > answer.txt` captures just the reply.

### Run CLI tests

```bash
source .venv/bin/activate
pytest tests/test_cli.py -v
```
All CLI tests are fully mocked — no real provider, network, or API key is required.

---

## 19. Validate Milestone 18 — Saved Searches & Saved Actions

> **v1 supports saved _file_ searches only.** Saved web searches are not part of this milestone (no web-search backend exists yet). A saved search's `target` must be `files`.

### Saved file searches

```bash
# Create a saved file search (glob query; optional path scopes it to an allowlisted root)
curl -s -X POST localhost:8000/saved/searches \
  -H 'Content-Type: application/json' \
  -d '{"name":"markdown","query":"*.md","path":"data"}' | python3 -m json.tool

curl -s localhost:8000/saved/searches | python3 -m json.tool              # list
curl -s -X POST localhost:8000/saved/searches/<id>/run | python3 -m json.tool   # run -> matching paths
curl -s -X DELETE localhost:8000/saved/searches/<id>

# A non-files target is rejected (web searches are out of scope in v1):
curl -s -X POST localhost:8000/saved/searches \
  -H 'Content-Type: application/json' \
  -d '{"name":"web","query":"cats","target":"web"}'    # -> 400
```

### Saved actions

```bash
curl -s -X POST localhost:8000/saved/actions \
  -H 'Content-Type: application/json' \
  -d '{"name":"standup","prompt":"Summarise my open tasks","mode":"budget-first"}' | python3 -m json.tool

curl -s -X POST localhost:8000/saved/actions/<id>/run | python3 -m json.tool
```
Running an action sends its prompt through the active provider chain (same router as `/chat`); the response includes `provider`, `model`, and `success`. Auto-extraction is not run on saved-action runs.

### Notes

- Saved items live under `profiles/<name>/saved/` and are included in backups automatically.
- Running a saved file search uses the existing file allowlist, so its path-traversal/permission guards apply unchanged.

### Run Milestone 18 tests

```bash
source .venv/bin/activate
pytest tests/test_saved_items.py tests/test_saved_api.py -v
```

---

## 20. Validate Milestone 19 — Settings panel (UI)

The Settings panel is a **read-only** view in the browser UI, built on the same pattern as the Memory panel. No new endpoints — it reads existing ones.

1. Start the server (`task run` or `uvicorn main:app`) and open the app in a browser.
2. Click the **⚙** button in the header (next to **Memory**). The Settings panel slides in from the right; opening it closes the Memory panel (one panel at a time).
3. Check the three tabs:
   - **Profile** — assistant name, version, routing mode, preferred provider, allowed tools, memory config (from `GET /profile` + `GET /health`).
   - **Providers** — every provider's enabled/available state, cost tier, and type (from `GET /providers`).
   - **Integrations** — CalDAV / CardDAV / Nextcloud status (from `GET /status/dav`); disabled integrations show as such.
4. Close with the **✕** button.

Everything is read-only in this milestone — there are no editable settings (that's future work).

### Run Milestone 19 tests

```bash
source .venv/bin/activate
pytest tests/test_settings_ui.py -v
```
These are template-presence tests; JS behavior is not covered by the suite.

---

## 21. Validate Milestone 20 — History & Attachments panel (UI)

A **read-only** panel built on the Memory/Settings pattern. History is the current in-memory session only; "Files" is a read-only browse of allowlisted files. No new endpoints; no uploads.

1. Start the server and open the app; send a couple of messages.
2. Click the **🕘** button in the header. The panel opens (closing any other open panel).
3. **Conversation** tab: lists the session's messages with a count; click an item to scroll to that message; **Clear conversation** resets the session view (frontend only).
4. **Files** tab: lists allowlisted files (shallow `*` listing via `POST /files/search`); click a file to preview its contents (via `GET /files/read`). Directories / non-readable paths show a graceful "Can't preview" message.
5. Close with **✕**.

History is session-only (cleared on page refresh) and the Files tab is a simple list + preview — not a file manager. Persistent history and real uploads are future work.

### Run Milestone 20 tests

```bash
source .venv/bin/activate
pytest tests/test_history_ui.py -v
```
Template-presence only; JS behavior remains uncovered.

---

## 22. Validate Milestone 21 — Grok CLI / API transports

Grok is one provider with an explicit transport. **Default is CLI** — the API is opt-in.

### Default (CLI) — unchanged

```bash
curl -s localhost:8000/providers | python3 -m json.tool   # grok available only if the `grok` CLI is on PATH
```
With nothing configured, Grok uses the CLI path exactly as before.

### Switch to the API transport

Set it durably in `config/providers.yaml`:
```yaml
providers:
  adapters:
    grok:
      transport: api
```
…or override at runtime:
```bash
export GROK_TRANSPORT=api
export XAI_API_KEY=xai-...
# optional: export GROK_MODEL=grok-4.3
```
A chat routed to Grok then calls the OpenAI-compatible API (`https://api.x.ai/v1`). Precedence: `GROK_TRANSPORT` env → `providers.adapters.grok.transport` → default `cli`.

### Run Milestone 21 tests

```bash
source .venv/bin/activate
pytest tests/test_provider_grok.py -v
```
All Grok tests are fully mocked — no real CLI, network, or API key required.

---

## 23. Validate Milestone 22 — Provider latency diagnostics

Measure-only: this changes nothing about routing or performance. It exposes timing/attribution for each request to developers (no user-facing output, no HTTP endpoint in this milestone).

### See it in the logs

Run any chat (web `/chat`, `athena "..."`, or a saved-action run). At `info` you'll see a one-line summary, e.g.:
```
Router latency req=ab12cd selected=grok transport=api total_ms=842 attempts=2 trace=[claude/cli unavailable 0ms; grok/api ok 842ms]
```
plus per-attempt durations on the existing `Router: provider 'X' succeeded (… Nms)` lines. No prompt/response content is logged.

### Inspect the trace programmatically

`ProviderRouter.route(...)` attaches the full trace to `response.metadata["diagnostics"]`:
```python
trace = response.metadata["diagnostics"]
# { request_id, total_ms, mode, attempt_order, selected,
#   records: [ {provider, transport, model, duration_ms, outcome, error_kind, ...} ] }
```
The last N traces are also kept in a bounded in-memory store (`diagnostics.store.get_diagnostics_store().recent()`). This data feeds the M24/M25 status work; it is not shown to end users in M22.

### Configure / disable

In `config/providers.yaml` under `providers.diagnostics`: `enabled` (default true), `ring_buffer_size` (50), `log_level` (info|debug).

### Run Milestone 22 tests

```bash
source .venv/bin/activate
pytest tests/test_diagnostics.py -v
```
All diagnostics tests are fully mocked (deterministic timing via a patched clock).

---

## 24. Validate Milestone 23 — Hermes CLI provider

Hermes is opt-in, CLI-backed, and disabled + unranked by default.

### Enable it

1. Install Hermes (`hermes` on PATH).
2. In `config/providers.yaml`, set `enabled: true` on the `hermes` adapter.
3. Route to it: add `hermes` to a ranking, or set `preferred_provider: hermes` in a profile.

### Check availability

```bash
curl -s localhost:8000/providers | python3 -m json.tool   # 'hermes' shows available:true when the binary is on PATH
```

### Use it

With `preferred_provider: hermes`, send a chat; Athena runs `hermes chat -q "<prompt>"`, parses the answer from the Hermes box, and returns it. The latency summary log shows `hermes/cli` and a duration (M22). If Hermes' output format changes and the box isn't found, the full cleaned output is returned with `metadata.parse_mode = "raw"`.

### Run Milestone 23 tests

```bash
source .venv/bin/activate
pytest tests/test_provider_hermes.py -v
```
Fully mocked against real Hermes output samples — no Hermes install required.

---

## 25. Validate Milestone 24 — Web UI status/progress (text-only)

1. Start the server and open the app.
2. Send a message. While it runs, a small **"Working…"** line shows below the messages.
3. When the answer arrives, a concise muted summary appears under it, e.g.:
   - `Answered via grok/api in 0.8s.`
   - `claude/cli unavailable; answered via grok/api in 0.8s.`
   - `No provider answered.`

It's text-only (no progress bar or live timeline — that's M24.5). With `providers.diagnostics.enabled: false`, no summary is shown and chat still works. The data behind it is `ChatResponse.diagnostics` (the content-free M22 trace):

```bash
curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"message":"hello"}' | python3 -m json.tool   # note the "diagnostics" field
```

### Run Milestone 24 tests

```bash
source .venv/bin/activate
pytest tests/test_chat_status_ui.py -v
```
Backend forwarding + template-presence; JS behavior remains uncovered (a JS harness is M30).

---

## 26. Validate Milestone 24.5 — Enhanced diagnostics & provider timeline

1. Start the server and send a message.
2. **While it runs:** the "Working…" line shows an indeterminate progress bar (no fake percentage).
3. **When it completes**, a quiet diagnostics block appears under the answer:
   - the concise summary line (as in M24),
   - a compact **provider timeline** — one segment per attempt, width ∝ duration, coloured by outcome, answering provider highlighted; hover a segment for `provider/transport · time`,
   - a collapsed **Details** disclosure — expand for mode, total time, attempt order, and a per-attempt timing/outcome table.

Everything is reconstructed at completion from `ChatResponse.diagnostics` — no streaming/polling, no backend change since M24. With `providers.diagnostics.enabled: false`, none of it shows and chat still works.

### Run Milestone 24.5 tests

```bash
source .venv/bin/activate
pytest tests/test_diagnostics_ui.py -v
```
Contract (the trace exposes the keys the timeline/details read, preserved through `/chat`) + template-presence. The JS render isn't exercised (no JS runtime; a JS harness remains future work).

---

## 27. Validate Milestone 25 — CLI status/progress feedback

Run a prompt in a terminal and watch **stderr** (stdout stays the answer only):

```bash
athena "Summarise today's notes"            # interactive: spinner while running, then a one-line summary on stderr
athena --diagnostics "Summarise today"      # adds an expanded per-provider breakdown on stderr
athena --quiet "Summarise today"            # no spinner, no summary; just the answer on stdout
athena "Summarise" 2>/dev/null              # status suppressed; stdout unchanged (pipe-safe)
echo "$(athena --diagnostics 'hi')"         # captured stdout is the answer only; status went to stderr
```

- The spinner only animates on an interactive TTY; piped/redirected runs are silent unless `--diagnostics`.
- The summary mirrors the web wording: `Answered via grok/api in 0.8s.` / `claude/cli unavailable; answered via grok/api in 0.8s.`
- With `providers.diagnostics.enabled: false`, no summary prints and the answer is unaffected.

### Run Milestone 25 tests

```bash
source .venv/bin/activate
pytest tests/test_cli_status.py tests/test_cli.py -v
```
Pure formatter + spinner units (`test_cli_status.py`) and main() integration asserting stdout stays answer-only while status goes to stderr (`test_cli.py`). Fully mocked.

---

## 28. Validate Milestone 26 — Editable settings in the UI

In the browser, open Settings (⚙) → **Profile**. The system prompt, routing mode, and preferred provider are now editable; edit and click **Save settings**. The change persists and applies to the next message (no restart). Via curl:

```bash
# Update the editable fields (only these three are accepted)
curl -s -X PATCH localhost:8000/profile -H 'Content-Type: application/json' \
  -d '{"system_prompt":"Be terse.","mode":"quality-first","preferred_provider":""}' | python3 -m json.tool

# It persisted to disk:
grep -A2 '^routing' profiles/athena/profile.yaml

# Validation: an invalid mode is rejected (400) and nothing is written/changed
curl -s -o /dev/null -w '%{http_code}\n' -X PATCH localhost:8000/profile \
  -H 'Content-Type: application/json' -d '{"mode":"ultra-fast"}'   # → 400
```

- Only `system_prompt`, `mode`, and `preferred_provider` are editable; other fields in the body are ignored. `preferred_provider: ""` clears the override.
- Providers/Integrations tabs remain read-only. After a restart the saved values persist; the next CLI run picks them up.

### Run Milestone 26 tests

```bash
source .venv/bin/activate
pytest tests/test_settings_edit.py -v
```
Persistence + runtime application, and validation failures that write nothing and mutate nothing. Fully mocked.

---

## 29. Validate Milestone 26.1 — Settings UI & status fixes

These fix post-2.6.0 live-testing regressions whose root cause was **stale browser-cached static assets**.

1. **Cache-busting:** the `chat.css` / `chat.js` URLs on `/` carry `?v=<version>`, and static responses send a revalidation header:
   ```bash
   curl -s localhost:8000/ | grep -o '/static/js/chat.js?v=[0-9.]*'
   curl -sI localhost:8000/static/js/chat.js | grep -i cache-control   # → no-cache, must-revalidate
   ```
   If you upgraded an already-open tab, do one hard refresh (Cmd/Ctrl-Shift-R); versioned URLs prevent recurrence.
2. **Editable settings actually update:** Settings (⚙) → Profile shows a system-prompt textarea, a mode dropdown, and a preferred-provider dropdown. Change mode/preferred → Save → the tab re-renders from `/profile` with the saved values, and the next chat uses them.
3. **Startup provider chip:** with no preferred provider set, the header chip stays blank until a request selects one; set a preferred provider and it shows on load.
4. **Status indicator:** "Working…" + bar appear only while a request runs and clear on completion — no permanent idle line.

---

## 30. Validate Milestone 26.2 — Provider/config truthfulness & version consistency

1. **Effective provider transport.** With Grok's API transport configured (`.env`: `GROK_TRANSPORT=api` + `XAI_API_KEY=…`), the listing shows `api`, not `cli`:
   ```bash
   curl -s localhost:8000/providers | python3 -m json.tool   # grok → "type": "api"
   athena --list-providers                                    # TYPE column shows api for grok
   ```
   Availability is config-based (key present + `openai` installed) — no live network probe. The Settings → Providers tab shows e.g. `grok (low/api) · available`.
2. **Version consistency.** The startup log reads `Profile loaded: Athena (app v2.6.10, profile schema v1.0.0)`; `/health` returns the app version (single FastAPI source); Settings → Profile shows **App version** (2.6.10) and **Profile schema version** (1.0.0) as separate, clearly-labelled fields. `config/app.yaml` no longer carries a version.

### Run Milestone 26.2 tests

```bash
source .venv/bin/activate
pytest tests/test_provider_truthfulness.py -v
```
Grok reports `api`/`cli` per the configured transport; a static-transport provider is unchanged; `/health` equals the app version. Fully mocked (no network).

---

## 31. Validate Milestone 26.3 — File/history hygiene

Open Settings/History → **Files**. By default only user-appropriate files show; internal/ops artifacts (`logs/`, `audit/`, `data/carddav_staged`, `data/import_conflicts`, `data/restore_staging`, `data/exports`, `*.log`, `.gitkeep`, `*.pyc`) are hidden. The filter is a backend flag on `/files/search`, not browser-only:

```bash
# Default = full listing (backwards-compatible); internal artifacts appear
curl -s -X POST localhost:8000/files/search -H 'Content-Type: application/json' \
  -d '{"pattern":"*"}' | python3 -m json.tool
# User-facing view = internal/ops hidden
curl -s -X POST localhost:8000/files/search -H 'Content-Type: application/json' \
  -d '{"pattern":"*","exclude_internal":true}' | python3 -m json.tool
```

In the UI, the **"Show internal/ops files"** checkbox (default off) re-runs the search unfiltered and shows a "Showing internal/operational files" note. The allowlist and read/write/search security are unchanged — this is a view-level filter only.

### Run Milestone 26.3 tests

```bash
source .venv/bin/activate
pytest tests/test_files_hygiene.py -v
```
`_is_internal_path` classification + `/files/search` honouring `exclude_internal` (hidden when set, full listing by default). Fully mocked.

## 32. Validate Milestone 26.5 — Concurrency hardening

The server must stay responsive while a provider is answering. With a real (slow) provider configured, start the server, then in two terminals fire a chat and a health check at the same time — `/health` should return immediately, not wait for the chat:

```bash
# Terminal A — a slow chat (blocks on the provider for several seconds)
time curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"message":"write a long essay"}' >/dev/null

# Terminal B — fire this right after A starts; it should return in well under a second
time curl -s localhost:8000/health
```

Before M26.5 the `/health` call blocked for the full duration of the chat (the event loop was frozen). After M26.5 it returns immediately. The same holds for opening the Settings/Memory/History panels or loading a second tab while a chat is in flight.

The same guarantee applies to **every remote endpoint**: the CalDAV, CardDAV, and Nextcloud handlers (list/read/search/export/create/delete/merge) all run their network calls off the loop too, so browsing contacts or files while a chat runs no longer serialises. Only local-only operations (staged-merge list/get/discard, backup zip/diff on local disk) stay synchronous, since they never touch the network.

Timeout behaviour (intentional M26.5 bounded request time): a single `route()` call is capped at 130s — on timeout `/chat` returns `{"success": false, "response": "The request timed out."}` (HTTP 200, rendered as an error bubble) rather than hanging. `GET /providers` (and the `PATCH /profile` provider-name check) return 503 on their 15s timeout; CalDAV/CardDAV/Nextcloud endpoints return 504 on their 30s DAV timeout — with two deliberate contract-preserving exceptions: `GET /nextcloud/ping` returns `{"reachable": false, "error": "..."}` and `GET /caldav/export` returns an empty calendar rather than erroring.

### Run Milestone 26.5 tests

```bash
source .venv/bin/activate
pytest tests/test_concurrency.py -v
```
Proves `/health` stays responsive while a slow `/chat` **and** a slow CalDAV read run (the loop-not-blocked tests), and that forced route / auto-extract / `/providers` / DAV-read timeouts degrade cleanly (clean `success=false`, non-fatal memory hang, 503, 504 — never a hang or 500). Fully mocked; no real providers or network.

## 33. Validate Milestone 26.6 — CLI logging isolation & test-suite restoration

The one-shot CLI keeps **stdout answer-only** (logs go to stderr), and doing so must not corrupt other code's log handlers. Confirm the runtime split:

```bash
# stdout carries only the answer (logs suppressed to /dev/null)
python -m cli --no-memory "hi" 2>/dev/null
# logs appear on stderr, never stdout
python -m cli --no-memory --verbose "hi" >/dev/null
```

The full CLI suite is green again (previously 16 failed because the CLI clobbered pytest's log-capture handler on the shared `athena` logger):

```bash
source .venv/bin/activate
pytest tests/test_cli.py -v
```
`test_configure_cli_logging_only_touches_tagged_handler` is the regression guard — it asserts a foreign (untagged) handler on the `athena` logger keeps its stream while Athena's own tagged console handler is retargeted to stderr.

## 34. Validate Milestone 26.7 — Filesystem write-safety

Four write/traversal holes are closed. Each rejection is verifiable by curl:

```bash
# Memory category traversal → 400, and no file is written outside the memory dir
curl -s -X POST localhost:8000/memory -H 'Content-Type: application/json' \
  -d '{"category":"../evil","key":"k","value":"v"}'
# → {"detail":"Unknown category: '../evil'. Valid categories: preferences, workflows, ..."}
# A valid category still works:
curl -s -X POST localhost:8000/memory -H 'Content-Type: application/json' \
  -d '{"category":"facts","key":"k","value":"v"}'          # → 200

# zip_filename traversal in restore → 400
curl -s -X POST localhost:8000/backup/restore -H 'Content-Type: application/json' \
  -d '{"zip_filename":"../../etc/x.zip","confirm":false}'  # → {"detail":"Invalid backup filename."}

# diff_token is bound to its backup: a token from A.zip's diff cannot restore B.zip
# (GET /backup/exports/A.zip/diff → token; POST /backup/restore for B.zip with it → 409)
```

Zip-Slip: a backup whose members contain `../…` (or absolute) paths no longer writes outside the app root — those members are skipped, counted under a `rejected` field, and noted in the diff/restore `warnings`; legitimate in-root members restore normally.

### Run Milestone 26.7 tests

```bash
source .venv/bin/activate
pytest tests/test_write_safety.py -v
```
13 tests covering all four fixes: memory-category rejection (API + `_category_path`), Zip-Slip containment (relative and absolute escapes, via `BackupManager` on real temp zips), `diff_token`↔filename binding, and the `_safe_export_path` guard. Fully self-contained; no network.

## 35. Validate Milestone 26.8 — Provider robustness

**ChatGPT is bounded.** The API adapter now uses a timeout (default 120s, override with `OPENAI_TIMEOUT`) and `max_retries=0`; a stall returns a clean `success: false` with a "Timeout" message rather than hanging. (Same shape as Grok's API path.)

**Diagnostics report the real Grok transport.** With `GROK_TRANSPORT=api` and no `XAI_API_KEY`, the trace/`--diagnostics` breakdown reads `grok/api unavailable` (not `grok/cli`), pointing at the missing key.

**Routing-override typos fail loudly:**

```bash
# Unknown routing mode no longer silently inverts to the most-expensive order —
# the router logs "unknown routing mode … falling back to 'balanced'".

# Saved actions reject a bad mode / unknown provider (400):
curl -s -X POST localhost:8000/saved/actions -H 'Content-Type: application/json' \
  -d '{"name":"x","prompt":"p","mode":"budget_first"}'      # → 400 (invalid mode)
curl -s -X POST localhost:8000/saved/actions -H 'Content-Type: application/json' \
  -d '{"name":"x","prompt":"p","provider":"claud"}'         # → 400 (unknown provider)

# CLI --provider typo exits 2 with the available list:
python -m cli --provider claud "hi"
# → Error: unknown provider 'claud'. Available: chatgpt, claude, gemini, grok, ...
```

**CLI adapters** (`claude`/`gemini`/`grok`/`hermes`) now run their subprocess with `stdin=DEVNULL` (no hang on an interactive first-run prompt) and explicit `utf-8`/`replace` decoding (a stray byte can't fail a good run).

### Run Milestone 26.8 tests

```bash
source .venv/bin/activate
pytest tests/test_provider_robustness.py -v
```
11 tests: ChatGPT timeout/connection mapping + bounded-client kwargs, CLI-subprocess hardening (all four adapters), unknown-mode→balanced + warning, and the router reporting a dynamic adapter's real `transport()` on unavailable records. Saved-action validation lives in `test_saved_api.py`; `--provider` validation in `test_cli.py`.

## 36. Validate Milestone 26.9 — Calendar / DAV correctness

**ICS export no longer shifts times.** An event stored as `2026-06-15T10:00:00+02:00` exports as `DTSTART:20260615T080000Z` (correct UTC), a naive `…T10:00:00` exports as floating `…100000` (no `Z`), and date-only values stay `VALUE=DATE`. Text fields are RFC-5545 escaped, so a summary containing a newline/comma/semicolon can't inject or malform properties (applies to both ICS export and CalDAV `create_task`).

**DAV status snapshots are isolated.** `GET /status/dav` (and internal `get()`/`get_all()`) return deep copies — a consumer mutating a nested field can't corrupt the shared store.

**Nextcloud reads are bounded.** `read_file` streams and stops at the 2MB cap, so an oversized remote file is never fully buffered (returns `{"content": null, "note": "file too large (>2MB)"}`).

**Backup manifests carry the real version.** A new export's `app_version` matches `/health`'s version (verify: create a backup, then `GET /backup/exports/<name>/inspect`).

**Contacts keep multiple emails/phones.** A vCard with several `EMAIL`/`TEL` values round-trips through import→export without losing the extras.

### Run Milestone 26.9 tests

```bash
source .venv/bin/activate
pytest tests/test_dav_correctness.py -v
```
14 tests: ICS datetime formatting (offset / negative / naive / trailing-Z / date-only / unparseable), ICS text escaping (reconstruct + `create_task`), status-store deep-copy isolation, Nextcloud streamed size-cap, manifest `app_version`, and vCard multi-value round-trip. Self-contained; mocked `requests`/caldav; no network.

## 37. Validate Milestone 26.10 — Web UI correctness

All fixes are in the browser chat UI. To eyeball them (hard-refresh first — assets are cache-busted by version):

- **Failed answers aren't remembered.** Trigger a failure (no providers available) → the error bubble shows the provider message, **not** "Network error". Send another message — the failure is not replayed as prior context (check the `/chat` request's `history` in devtools: it contains only your user turns).
- **Resilient to a missing `voice.js`.** Even if `voice.js` fails to load, the send button, Enter key, and the Memory/Settings/History panels still work (init no longer aborts).
- **Settings save never silently clears a setting.** Open **Settings → Profile**. Even if the provider list can't load, the configured provider is shown (as "… (current)") and stays selected; saving only a system-prompt edit does not clear the provider or reset the mode. A muted note appears when the provider list is unavailable.
- **No stale panel content.** Rapidly switching Memory/Settings/History tabs never leaves one tab's content appended beneath another's.
- **Files counter is styled.** History → Files shows a muted "N files · click to preview" counter.

### Run Milestone 26.10 tests

```bash
source .venv/bin/activate
pytest tests/test_ui_correctness.py -v
```
7 source-structure guards (assistant-turn-on-success, scoped network catch, `typeof voice` guards, canonical-option injection, `_panelLoadToken` guards, tab-guarded post-save re-render, `.history-count`/`.settings-note` CSS). The repo has no JS runtime harness (a "JS/UI test harness" is on the "Later / unscheduled" list), so behaviour was verified live with headless Chromium (Playwright) during implementation — see `docs/TESTING.md`.
