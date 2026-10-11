-- The CRM, finance and revenue leave the control plane (owner direction 2026-10-11). The CRM runs from
-- its own repository (bookchaowalit/solo-crm) on its own Neon databases; the owner's revenue, invoices and
-- clients were imported into the income-pipeline CRM and are read and written through its ledger API
-- (infra/scripts/utils/crm_ledger.py, infra/scripts/cli/ledger-cli.py). Finance, job leads, outreach,
-- niches, assets and opportunities never held rows here; their local tooling was deleted. The agency
-- offers are seed rows the CRM databases carry themselves (migration 078 there).
-- Guard: the ledger rows go only after the cutover recorded a verified import ('crm-ledger' in
-- cell_cutovers, rows = clients + revenue + invoices), and every other table must be empty.
-- The migration runner applies this in one transaction; tables go children first, so no foreign key
-- action fires on a row that is kept.

CREATE TEMP TABLE retire_crm_guard (ok INTEGER NOT NULL CHECK (ok = 1));
INSERT INTO retire_crm_guard SELECT
    (SELECT count(*) FROM cell_cutovers WHERE cell = 'crm-ledger'
       AND rows = (SELECT count(*) FROM clients) + (SELECT count(*) FROM revenue) + (SELECT count(*) FROM invoices))
    * (((SELECT count(*) FROM asset_metrics)
    + (SELECT count(*) FROM assets)
    + (SELECT count(*) FROM crm_activities)
    + (SELECT count(*) FROM crm_agency_bookings)
    + (SELECT count(*) FROM crm_agency_consents)
    + (SELECT count(*) FROM crm_agency_deal_state)
    + (SELECT count(*) FROM crm_agency_documents)
    + (SELECT count(*) FROM crm_agency_invoice_links)
    + (SELECT count(*) FROM crm_agency_notifications)
    + (SELECT count(*) FROM crm_agency_slots)
    + (SELECT count(*) FROM crm_deals)
    + (SELECT count(*) FROM crm_workflow_evidence)
    + (SELECT count(*) FROM finance_account_aliases)
    + (SELECT count(*) FROM finance_accounts)
    + (SELECT count(*) FROM finance_budget_plans)
    + (SELECT count(*) FROM finance_cashflow_plans)
    + (SELECT count(*) FROM finance_investments)
    + (SELECT count(*) FROM finance_liabilities)
    + (SELECT count(*) FROM finance_market_price_snapshots)
    + (SELECT count(*) FROM finance_reconciliations)
    + (SELECT count(*) FROM finance_subscription_aliases)
    + (SELECT count(*) FROM finance_subscription_reviews)
    + (SELECT count(*) FROM finance_subscriptions)
    + (SELECT count(*) FROM finance_tax_items)
    + (SELECT count(*) FROM finance_valuation_snapshots)
    + (SELECT count(*) FROM financial_transactions)
    + (SELECT count(*) FROM job_leads)
    + (SELECT count(*) FROM niches)
    + (SELECT count(*) FROM opportunities)
    + (SELECT count(*) FROM opportunity_actions)
    + (SELECT count(*) FROM outreach_logs)) = 0);
DROP TABLE retire_crm_guard;

DROP TABLE IF EXISTS crm_agency_invoice_links;
DROP TABLE IF EXISTS crm_agency_documents;
DROP TABLE IF EXISTS crm_agency_notifications;
DROP TABLE IF EXISTS crm_agency_bookings;
DROP TABLE IF EXISTS crm_agency_slots;
DROP TABLE IF EXISTS crm_agency_consents;
DROP TABLE IF EXISTS crm_agency_deal_state;
DROP TABLE IF EXISTS crm_workflow_evidence;
DROP TABLE IF EXISTS crm_activities;
DROP TABLE IF EXISTS outreach_logs;
DROP TABLE IF EXISTS crm_deals;
DROP TABLE IF EXISTS crm_agency_offers;
DROP TABLE IF EXISTS invoices;
DROP TABLE IF EXISTS revenue;
DROP TABLE IF EXISTS asset_metrics;
DROP TABLE IF EXISTS assets;
DROP TABLE IF EXISTS opportunity_actions;
DROP TABLE IF EXISTS opportunities;
DROP TABLE IF EXISTS job_leads;
DROP TABLE IF EXISTS niches;
DROP TABLE IF EXISTS finance_account_aliases;
DROP TABLE IF EXISTS finance_accounts;
DROP TABLE IF EXISTS finance_budget_plans;
DROP TABLE IF EXISTS finance_cashflow_plans;
DROP TABLE IF EXISTS finance_investments;
DROP TABLE IF EXISTS finance_liabilities;
DROP TABLE IF EXISTS finance_market_price_snapshots;
DROP TABLE IF EXISTS finance_reconciliations;
DROP TABLE IF EXISTS finance_subscription_aliases;
DROP TABLE IF EXISTS finance_subscription_reviews;
DROP TABLE IF EXISTS finance_subscriptions;
DROP TABLE IF EXISTS finance_tax_items;
DROP TABLE IF EXISTS finance_valuation_snapshots;
DROP TABLE IF EXISTS financial_transactions;
DROP TABLE IF EXISTS clients;
