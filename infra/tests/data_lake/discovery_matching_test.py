import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))
from discovery.profile import enrich, load_profile, match_item  # noqa: E402


NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


def item(**updates):
    value = {
        "id": "x", "title": "Test", "category": "postgraduate", "status": "open",
        "eligible_countries": ["TH"], "eligibility_text": "Applicants must meet the program terms.",
        "deadline": {"kind": "fixed", "at": "2026-09-20T00:00:00Z"},
        "value": {"kind": "cash", "amount": 100, "currency": "USD", "guaranteed": False},
        "terms": {"study_level": "postgraduate", "applicant_type": "individual", "startup_stage": None, "incorporation_required": None},
    }
    value.update(updates)
    return value


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"profile_version": "discovery.profile.v1", "country": "TH", "study_level": "postgraduate", "student_status": "unknown", "applicant_type": "individual", "startup_stage": "unknown", "has_legal_entity": None, "beneficiary_groups": []}

    def test_known_terms_are_possible_even_if_selection_is_not_guaranteed(self):
        result = match_item(item(), self.profile, now=NOW)
        self.assertEqual(result["match"], "possible")

    def test_unknown_term_is_not_promoted_to_possible(self):
        candidate = item(terms={"study_level": None, "applicant_type": None, "startup_stage": None, "incorporation_required": None})
        result = match_item(candidate, self.profile, now=NOW)
        self.assertEqual(result["match"], "unknown")
        self.assertIn("study_level", result["missing_fields"])

    def test_country_mismatch_is_hard_conflict(self):
        self.assertEqual(match_item(item(), dict(self.profile, country="GB"), now=NOW)["match"], "not_eligible")

    def test_study_mismatch_is_hard_conflict(self):
        self.assertEqual(match_item(item(), dict(self.profile, study_level="undergraduate"), now=NOW)["match"], "not_eligible")

    def test_missing_country_is_unknown(self):
        result = match_item(item(), dict(self.profile, country=None), now=NOW)
        self.assertEqual(result["match"], "unknown")
        self.assertIn("country", result["missing_fields"])

    def test_incorporation_requirement(self):
        candidate = item(terms={"study_level": None, "applicant_type": None, "startup_stage": "seed", "incorporation_required": True})
        result = match_item(candidate, dict(self.profile, has_legal_entity=False, startup_stage="seed", study_level=None, applicant_type=None), now=NOW)
        self.assertEqual(result["match"], "not_eligible")

    def test_closed_and_expired_are_not_open(self):
        self.assertEqual(match_item(item(status="closed"), self.profile, now=NOW)["match"], "not_open")
        self.assertEqual(match_item(item(deadline={"kind": "fixed", "at": "2026-09-06T00:00:00Z"}), self.profile, now=NOW)["match"], "not_open")

    def test_unknown_deadline_is_unknown(self):
        result = match_item(item(deadline={"kind": "unknown", "at": None}), self.profile, now=NOW)
        self.assertEqual(result["match"], "unknown")
        self.assertIsNone(result["days_remaining"])

    def test_future_availability_is_not_open(self):
        result = match_item(item(deadline={"kind": "unknown", "at": None}, availability={"kind": "scheduled", "starts_at": "2026-10-01T00:00:00Z", "ends_at": None}), self.profile, now=NOW)
        self.assertEqual(result["match"], "not_open")
        self.assertGreater(result["days_until_start"], 0)

    def test_deadline_queue_is_bounded(self):
        rows = [{"product": "p", "item": item()}, {"product": "p", "item": item(id="late", deadline={"kind": "fixed", "at": "2026-12-20T00:00:00Z"})}]
        self.assertEqual(len(enrich(rows, self.profile, now=NOW, deadline_within_days=20)), 1)

    def test_profile_schema_rejects_extra_private_fields(self):
        profile = json.loads((ROOT / "templates" / "discovery-profile.example.json").read_text())
        profile["email"] = "should-not-be-stored"
        temporary = ROOT / "data" / "exports" / "_discovery-profile-test.json"
        temporary.write_text(json.dumps(profile))
        try:
            with self.assertRaises(ValueError): load_profile(temporary)
        finally:
            temporary.unlink()


if __name__ == "__main__": unittest.main()
