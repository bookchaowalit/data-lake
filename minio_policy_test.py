#!/usr/bin/env python3
"""Offline least-privilege contract tests for the MinIO lake policies."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
POLICY_DIR = ROOT / "infra" / "self-hosted-stack" / "minio" / "policies"
POLICIES = {
    "lake-ingest": POLICY_DIR / "lake-ingest.json",
    "lake-transform": POLICY_DIR / "lake-transform.json",
    "lake-consumer": POLICY_DIR / "lake-consumer.json",
    "lake-operator": POLICY_DIR / "lake-operator.json",
}
BUCKET_ARN = "arn:aws:s3:::solo-empire-portfolio"
OBJECT_ARN = BUCKET_ARN + "/lake/"


def load_policy(name: str) -> dict[str, Any]:
    payload = json.loads(POLICIES[name].read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"{name} policy must be an object")
    return payload


def statements(policy: dict[str, Any]) -> list[dict[str, Any]]:
    value = policy.get("Statement")
    if not isinstance(value, list):
        raise AssertionError("policy Statement must be a list")
    return value


def actions(policy: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for statement in statements(policy):
        value = statement.get("Action", [])
        result.update(value if isinstance(value, list) else [value])
    return result


def resources(policy: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for statement in statements(policy):
        value = statement.get("Resource", [])
        result.extend(value if isinstance(value, list) else [value])
    return result


class MinioPolicyTests(unittest.TestCase):
    def test_documents_are_explicit_and_scoped(self):
        for name in POLICIES:
            policy = load_policy(name)
            self.assertEqual(policy.get("Version"), "2012-10-17")
            self.assertTrue(statements(policy))
            self.assertNotIn("s3:*", actions(policy), name)
            self.assertNotIn("*", actions(policy), name)
            for statement in statements(policy):
                self.assertEqual(statement.get("Effect"), "Allow", name)
                self.assertTrue(statement.get("Sid"), name)
            for resource in resources(policy):
                if name != "lake-operator" or resource != "*":
                    self.assertTrue(
                        resource == BUCKET_ARN or resource.startswith(OBJECT_ARN),
                        f"{name} has unscoped resource {resource!r}",
                    )

    def test_ingest_can_only_touch_ingest_layers(self):
        policy = load_policy("lake-ingest")
        self.assertIn("s3:PutObject", actions(policy))
        self.assertIn("s3:GetObject", actions(policy))
        scoped = resources(policy)
        self.assertTrue(all("/lake/landing/" in item or "/lake/bronze/" in item or "/lake/control/" in item for item in scoped))
        self.assertFalse(any("/lake/silver/" in item or "/lake/gold/" in item for item in scoped))
        self.assertNotIn("s3:DeleteObject", actions(policy))
        self.assertNotIn("s3:ListBucket", actions(policy))

    def test_transform_reads_bronze_and_writes_derived_layers(self):
        policy = load_policy("lake-transform")
        scoped = resources(policy)
        self.assertTrue(any("/lake/bronze/" in item for item in scoped))
        self.assertTrue(any("/lake/silver/" in item for item in scoped))
        self.assertTrue(any("/lake/gold/" in item for item in scoped))
        self.assertTrue(any("/lake/control/manifests/derived/" in item for item in scoped))
        self.assertFalse(any("/lake/landing/" in item for item in scoped))
        self.assertNotIn("s3:DeleteObject", actions(policy))

    def test_consumer_is_gold_read_only(self):
        policy = load_policy("lake-consumer")
        scoped = resources(policy)
        self.assertTrue(scoped)
        self.assertTrue(all("/lake/gold/" in item or item == BUCKET_ARN for item in scoped))
        self.assertEqual(actions(policy), {"s3:ListBucket", "s3:GetObject"})
        self.assertNotIn("s3:PutObject", actions(policy))
        self.assertNotIn("s3:DeleteObject", actions(policy))

    def test_operator_is_explicitly_broader_but_still_bucket_scoped(self):
        policy = load_policy("lake-operator")
        self.assertIn("s3:PutBucketVersioning", actions(policy))
        self.assertIn("s3:PutLifecycleConfiguration", actions(policy))
        self.assertIn("s3:DeleteObject", actions(policy))
        self.assertNotIn("iam:*", actions(policy))
        self.assertTrue(all(item == BUCKET_ARN or item.startswith(OBJECT_ARN) for item in resources(policy)))

    def test_policy_files_do_not_contain_secret_values(self):
        forbidden = ("MINIO_ROOT_PASSWORD", "AWS_SECRET_ACCESS_KEY", "token=", "password=")
        for path in POLICIES.values():
            text = path.read_text(encoding="utf-8").lower()
            for marker in forbidden:
                self.assertNotIn(marker.lower(), text, str(path))


if __name__ == "__main__":
    unittest.main()
