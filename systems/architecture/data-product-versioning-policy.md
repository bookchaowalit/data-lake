---
title: Data Product Versioning Policy
aliases: [Data Product Contracts, Schema Freeze]
tags: [architecture, data-products, contracts, versioning]
created: 2026-08-04
updated: 2026-09-08
description: Frozen v2 port map for local free-only data-product APIs and consumers.
related: [data-product-portfolio, data-product-contracts-v2, data-product-contracts-v1, CODING-AGENT-DATA-PRODUCT-API-FREE-PLAN]
---

# Data Product Versioning Policy

## Intent

Keep domain data products and application consumers compatible without silent
breakage. Generation **v1** remains an archival freeze; generation **v2** is
the active freeze after retiring the cross-domain opportunity synthesis API.

Machine-readable freeze:

- [`data-product-contracts-v2.yaml`](data-product-contracts-v2.yaml)

Guard:

```bash
task contracts:check
# also runs as part of: task docs:check
```

## Frozen v2 port and schema map

| ID | Port | schema_version | Repository | Role |
|---|---|---|---|---|
| crypto | 8101 | `crypto.v1` | `book-crypto-data` | domain source |
| stocks | 8102 | `stock.v1` | `book-stock-data` | domain source |
| fx | 8103 | `fx.v1` | `book-fx-data` | domain source |
| defi | 8104 | `defi.v1` | `book-defi-data` | domain source |
| flights | 8105 | `flight.v1` | `book-flight-data` | domain source |
| seo | 8106 | `seo.v1` | `book-seo-data` | domain source |
| ai_tools | 8107 | `ai_tools.v1` | `book-ai-tools-data` | domain source |

Default bind: **`127.0.0.1` only**.

## Envelope contract (all products)

Every data response uses these **required keys**:

```text
schema_version
source
retrieved_at
data_status
items
next_cursor
```

Optional diagnostic fields (`error`, `detail`) must never carry secrets and
must not be required by consumers.

## HTTP contract

| Method | Path | Rule |
|---|---|---|
| GET | `/healthz` | No upstream scrape |
| GET | `/v1/metadata` | Envelope + local metadata |
| GET | `/v1/records` | Envelope of records |
| GET | `/v1/records/{id}` | Single record or 404 |
| GET | `/v1/history` | History envelope |
| POST | `/v1/refresh` | **403 by default** |

Consumers may call **GET only**. They must not scrape upstream sources or
perform external writes.

## Free-only defaults (frozen)

```text
FREE_ONLY=true
ALLOW_PAID_PROVIDERS=false
ALLOW_EXTERNAL_WRITES=false
ALLOW_REFRESH=false
```

## What is a breaking change?

Any of the following **must not** ship as the same `*.v1` schema:

- Removing or renaming a required envelope key
- Changing `schema_version` string meaning without a new version id
- Reassigning a reserved port (8101–8107) to a different product
- Changing default bind to non-loopback
- Making `POST /v1/refresh` succeed by default
- Requiring paid credentials for the free default path
- Enabling external writes (Telegram, Todoist, email, etc.) by default
- Removing GET endpoints listed above
- Changing `source` identity away from the repository name without version bump

### Additive (non-breaking) changes allowed under the same `*.v1`

- New optional fields **inside** `items[]` objects
- New optional top-level keys **beyond** the required six (consumers ignore unknowns)
- New optional query parameters with defaults preserving prior behavior
- Documentation and fixture updates that still validate against the freeze

## Required process for breaking changes

1. Propose a **new** schema id for a domain payload change, such as `crypto.v2`.
2. Keep serving the previous version until consumers migrate (dual-publish if needed).
3. Update the active contract map only by adding a **new freeze file** (for
   example `data-product-contracts-v3.yaml`), never by editing frozen rows in
   place.
4. Update producer config, fixtures, consumer catalogs, and compatibility tests
   in the same change set.
5. Run:

```bash
task contracts:check
task docs:check
# plus each affected repo's unit tests
```

## Compatibility matrix (v2 consumers)

| Consumer | Expects ports | Expects schemas |
|---|---|---|
| `insights-dashboard` | 8101–8107 | seven domain `*.v1` |
| `bookchaowalit-portfolio-frontend` | 8101–8107 | seven domain `*.v1` |

Both consumers also support the additive `news.v1` (`:8108`) and
`discovery.v1` (`:8110`) contracts; those ports are intentionally outside the
frozen seven-product v2 map.

The seven-product v2 rows remain frozen. The additive news domain is tracked
separately by [`news-data-contract-v1.yaml`](news-data-contract-v1.yaml):
`book-news-scraping` serves `news.v1` on `:8108` and does not reassign any
reserved v2 port.
The additive technology-discovery domain is tracked separately by
[`discovery-data-contract-v1.yaml`](discovery-data-contract-v1.yaml):
`book-discovery-data` serves `discovery.v1` on `:8110` and does not reassign
any reserved v2 port. Both additive contracts are consumed alongside, but do
not mutate, the seven frozen v2 rows.

## Enforcement

| Layer | Mechanism |
|---|---|
| Solo Empire control plane | `data_product_contract_guard.py` via `task contracts:check` / `task docs:check` |
| Producers (7 APIs) | `tests/test_contract_freeze.py` in each repo |
| Insights / portfolio | contract freeze unit tests against catalog |

## Safety

- Free-plan / local-first only for the default path
- No paid API requirement in v1 free defaults
- No production public bind in the freeze
- No commit/push/deploy is implied by this policy document
