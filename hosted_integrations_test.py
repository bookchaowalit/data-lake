#!/usr/bin/env python3
"""Offline tests for the hosted-integration readiness contract."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.hosted_integrations import readiness_report  # noqa: E402


class HostedIntegrationTests(unittest.TestCase):
    def test_empty_environment_does_not_print_or_require_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            report = readiness_report()
        self.assertEqual(report["configured_count"], 0)
        self.assertTrue(all(not row["present_names"] for row in report["integrations"]))

    def test_all_supported_free_lanes_report_configured(self):
        values = {
            "SOLO_EMPIRE_DATA_LAKE_URI": "s3://portfolio",
            "DATA_LAKE_S3_ENDPOINT": "https://account.r2.cloudflarestorage.com",
            "AWS_ACCESS_KEY_ID": "r2-access",
            "AWS_SECRET_ACCESS_KEY": "r2-secret",
            "ICEBERG_CATALOG_URI": "https://catalog.example.com/v1",
            "ICEBERG_WAREHOUSE_URI": "portfolio",
            "ICEBERG_CATALOG_TOKEN": "catalog-token",
            "GOOGLE_CLOUD_PROJECT": "portfolio-project",
            "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/credentials.json",
            "NEON_DATA_LAKE_CATALOG_URL": "postgresql+psycopg2://user:pass@host/db",
            "PREFECT_API_URL": "https://api.prefect.cloud/api/accounts/a/workspaces/w",
            "PREFECT_API_KEY": "prefect-token",
            "GRAFANA_CLOUD_OTLP_ENDPOINT": "https://otlp.example.com",
            "GRAFANA_CLOUD_API_KEY": "grafana-token",
            "GITHUB_ACTIONS": "true",
            "CLOUDFLARE_ACCOUNT_ID": "account",
            "CLOUDFLARE_API_TOKEN": "cloudflare-token",
            "CLOUDFLARE_PAGES_PROJECT": "solo-empire-docs",
            "TURNSTILE_SITE_KEY": "site-key",
            "TURNSTILE_SECRET_KEY": "turnstile-secret",
            "VERCEL_TOKEN": "vercel-token",
            "VERCEL_PROJECT_ID": "vercel-project",
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_ANON_KEY": "supabase-anon-key",
            "CLOUD_RUN_SERVICE": "solo-empire-api",
            "UPSTASH_REDIS_REST_URL": "https://redis.upstash.io",
            "UPSTASH_REDIS_REST_TOKEN": "redis-token",
            "RESEND_API_KEY": "re-token",
            "POSTHOG_HOST": "https://app.posthog.com",
            "POSTHOG_API_KEY": "phc-test",
            "SENTRY_DSN": "https://public@example.ingest.sentry.io/1",
            "INFISICAL_SITE_URL": "https://app.infisical.com",
            "INFISICAL_PROJECT_ID": "project",
            "INFISICAL_ENVIRONMENT": "dev",
            "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID": "client",
            "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET": "client-secret",
        }
        with patch.dict(os.environ, values, clear=False):
            report = readiness_report()
        statuses = {str(row["id"]): row["status"] for row in report["integrations"]}
        self.assertTrue(all(status == "configured" for status in statuses.values()))

    def test_partial_configuration_is_visible(self):
        with patch.dict(
            os.environ,
            {
                "PREFECT_API_URL": "https://api.prefect.cloud/api",
                "PREFECT_API_KEY": "",
            },
            clear=False,
        ):
            report = readiness_report()
        prefect = next(row for row in report["integrations"] if row["id"] == "prefect-cloud")
        self.assertEqual(prefect["status"], "not_configured")
        self.assertIn("PREFECT_API_KEY", prefect["missing_names"])


if __name__ == "__main__":
    unittest.main()
