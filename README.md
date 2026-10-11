# solo-data-lake

Pipeline และ collector ของ lake-first data products ของ Solo Empire: landing → Bronze Parquet → Silver, scraping coverage/health, scheduled capture (news/market/SEO/jobs), discovery portfolio, Telegram/Brave collectors, diary intake, และ dbt projection

ที่มา: ย้ายจาก `solo-empire` เมื่อ 2026-10-11 พร้อมประวัติ git ของ `infra/scripts/data_lake`, `infra/scripts/discovery`, `infra/scripts/opportunities`, `infra/tests/data_lake`, `infra/dbt`.
repo นี้คงโครงสร้าง `infra/...` เดิมไว้ เพื่อให้ `ROOT = parents[3]` และ path ใน test ทำงานเหมือนเดิม.

- `infra/scripts/data_lake/` — 47 modules (ingest/storage/query/silver/product_adapter ฯลฯ + run_* capture + cron setup)
- `infra/scripts/{discovery,opportunities}/`, `infra/scripts/sync/{sync_brave_bookmarks,brave_bookmark_workflow,organize_brave_bookmarks,telegram_channels,telegram_personal}.py`, `infra/scripts/cli/diary-intake-cli.py`
- `infra/scripts/utils/` — สำเนา vendored ของ utils ที่โค้ดข้างบนต้องใช้ (`_env`, `cell_store`, `task_store`, `secret_resolver`, `job_client`, `data_product_contract_guard`, …)
- `infra/dbt/` — dbt projection (`dbt_lake_test.py`)
- `infra/tests/` — test ทั้งหมดของโค้ดข้างต้น
- ผลิตภัณฑ์ข้อมูล `job.v1` (ผู้บริโภคคือ `book-job-data` และ `solo-crm` job-radar) — `book-job-data` ยังเป็น repo ของตัวเอง; ที่นี่มีเฉพาะ adapter/readiness/e2e

## ความสัมพันธ์กับ repo อื่น

- `solo-empire-data-lake` (public) เป็น runtime แพ็กเกจพกพา; README ของมันระบุว่า "parent `infra/scripts/data_lake`" เป็น canonical สำหรับ 9 modules ที่ใช้ร่วม — canonical นั้นย้ายมาที่ `infra/scripts/data_lake/` ใน repo นี้แล้ว (ต้องแก้ `scripts/check_parity.py` ของ public repo ให้ชี้มาที่นี่ — ยังไม่ได้ทำ)
- `solo-event-hub` มีสำเนา vendored ของ ingest/storage/parquet/iceberg

## Workspace overlay

Tests/โค้ดอ้าง path ของ product repos และ contract ใน solo-empire (`projects/`, `systems/`, `templates/`, `repository-catalog/`, `infra/database/`). ตั้งลิงก์ (gitignored) ด้วย:

```bash
bash scripts/link-overlay.sh            # SOLO_EMPIRE_ROOT=~/solo-empire โดยปริยาย
ln -s ~/solo-empire/.venv .venv         # หรือ python3 -m venv .venv && pip install -r infra/requirements-data-lake.txt
```

## ทดสอบ

```bash
for t in infra/tests/data_lake/*_test.py; do python3 $t || echo "FAIL $t"; done
```

ข้อจำกัดที่ทราบ: `discovery_portfolio_test`, `scraping_coverage_test`, `scraping_dry_run_test` ตรวจ boundary ของ path หลัง `resolve()` จึงไม่ผ่านเมื่อ `projects/` เป็น symlink (ผ่านเมื่ออยู่ใน workspace จริงก่อนย้าย). `scraping_capture_ingest_test`, `job_scraper_import_test`, `news_capture_runtime_test`, `dbt_lake_test` (ใน solo-empire), brave/telegram/diary tests ล้มเหลวอยู่แล้วก่อนย้าย (ขาด pyarrow/ค่า env) — ดูผลเปรียบเทียบใน handoff.
