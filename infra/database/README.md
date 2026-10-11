# Retired control-plane database

The local SQLite control plane database was retired on 2026-10-11.
Every domain now lives in its own cell (repository, Railway API, Neon); see
[`online-systems.yaml`](../../repository-catalog/registries/online-systems.yaml).
The last copy was archived outside the repository with the SQLite backup API
(`~/.local/share/solo-empire/archive/solo-empire-retired-2026-10-11.db`, owner-only).

What stays here is history, not runtime:

- `migrations/` — the applied migration history (001–088). The event hub image still
  copies `033_source_registry_intake_queue.sql` for its own `hub.db`.
- `schema.sql` — the last schema dump; tests build their SQLite doubles from it.

No code may open a control-plane database; the task writer guard
(`infra/scripts/utils/task_writer_guard.py`) rejects SQL on the retired tables.
