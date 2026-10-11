# Telegram Personal Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a private Telegram user-account manager that synchronizes bounded chat history, supports local search and triage, creates reply drafts, and requires explicit approval before sending.

**Architecture:** Extend the existing Telethon user-session boundary with a separate personal-manager state directory and private data-lake dataset. The manager never auto-sends: outbound actions are stored as approval records containing a target, exact message fingerprint, and expiry, and the send command verifies those fields before calling Telegram. Offline read/search/draft operations work against captured data and do not call Telegram.

**Tech Stack:** Python 3 stdlib, optional Telethon 1.44, existing data-lake ingest helper, JSON state with mode 0700, Taskfile integration, unittest fixtures.

**Spec:** User request in the conversation: “ให้ AI เป็นเลขาส่วนตัวคอยอ่าน Telegram ทั้งบัญชี, สรุป, หาเรื่องสำคัญ, draft reply และตอบบางข้อความแทนเรา” with approval levels and privacy boundaries.

## Global Constraints

- Use `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` only through the existing secret resolver; never print or persist them.
- Use a Telegram user session, never a Bot API token, and reject bot accounts.
- Read/sync is bounded and idempotent; lake ingestion must succeed before cursors advance.
- Private message data and session files remain local with mode 0700; no raw payloads in logs or telemetry.
- Sending is disabled unless an explicit, non-expired approval record matches the exact target and message fingerprint.
- Offline tests use synthetic messages and make no Telegram calls.

### Task 1: Personal manager core and offline contracts

**Files:**
- Create: `infra/scripts/sync/telegram_personal.py`
- Test: `infra/tests/integrations/telegram_personal_test.py`

**Interfaces:**
- `validate_config(config) -> dict`
- `classify_message(text, *, is_outgoing=False, mentions_me=False) -> str`
- `build_draft(message, *, tone="concise") -> dict`
- `create_approval(state_dir, *, chat_id, message_id, text, ttl_seconds=900) -> dict`
- `verify_approval(state_dir, approval_id, *, chat_id, text) -> dict`
- `search_messages(lake_dir, *, keyword="", limit=20, priority="") -> list[dict]`
- `send_approved(...)` calls a narrow injected client method only after verification.

- [x] Write failing tests for config bounds, priority classification, deterministic draft, approval fingerprint/expiry, and offline search.
- [x] Run the focused test and observe failure because the module is absent.
- [x] Implement the smallest pure functions and local state helpers.
- [x] Run focused tests until green.

### Task 2: Telethon sync and command surface

**Files:**
- Modify: `infra/scripts/sync/telegram_personal.py`
- Modify: `infra/tasks/integrations.yml`
- Test: `infra/tests/integrations/telegram_personal_test.py`

**Interfaces:**
- Commands: `setup`, `sync`, `status`, `read`, `draft`, `approve`, `send`.
- `sync` uses `TelegramClient.iter_dialogs` and `iter_messages` with bounded limits and durable pending batches.
- `send` requires `--approval-id`, `--chat-id`, and `--text`; no implicit send path.

- [x] Add fake-client tests for bounded sync and “bot account rejected”.
- [x] Run focused tests and observe the new command behavior failures.
- [x] Implement Telethon imports lazily, account login in a real terminal, state lock, checkpoint replay, and lake ingestion.
- [x] Implement approval-gated send with safe error classes and no response-body logging.
- [x] Run focused tests and confirm offline suite remains network-free.

### Task 3: Documentation and registration

**Files:**
- Modify: `infra/README.md`
- Modify: `operations/runbooks/TELEGRAM-CHANNEL-TRACKING.md`
- Modify: `infra/tasks/integrations.yml`
- Create: `operations/runbooks/TELEGRAM-PERSONAL-MANAGER.md`

**Interfaces:**
- Document install/setup commands, secret names, local state paths, privacy/retention, approval levels, and the fact that live login requires the owner’s terminal.

- [x] Add task aliases and the personal-manager runbook.
- [x] Add a short link from the existing Telegram integration README/runbook.
- [x] Run docs checks for catalog/entity drift and correct generated indexes if required.

### Task 4: Verification and diary

**Files:**
- No production files beyond the task files above.

- [x] Run focused personal Telegram tests, existing Telegram tests, `task test`, `task typecheck`, `task docs:check`, and `git diff --check`.
- [x] Record the conversation in the private daily diary without secrets or raw message text.
- [x] Report what is implemented and the live-login/token prerequisites without claiming a live account connection.
