from __future__ import annotations
import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/opportunities/import_job_applications.py'
SPEC = importlib.util.spec_from_file_location('job_application_import', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ConfirmedApplicationImportTests(unittest.TestCase):
    def row(self):
        now = datetime.now(timezone.utc)
        return dict(schema_version='confirmed-application.v1', status='submitted',
                    url='https://example.test/jobs/123', company='Fixture', title='Engineer',
                    submitted_at=now.isoformat(), followup_date=(now.date()+timedelta(days=7)).isoformat(),
                    receipt_sha256='a'*64, resume_sha256='b'*64,
                    cover_letter_sha256='c'*64, packet_sha256='d'*64)

    def tracker(self):
        return ('# Application Tracker\n\n## Current applications\n\n'
                '| Application ID | Opportunity ID | Platform | Company | Role | Applied date | Status | Follow-up date | Notes |\n'
                '|---|---|---|---|---|---|---|---|---|\n' + module.PLACEHOLDER +
                '\n\n## Application status values\n\nKeep this content.\n')

    def test_receipt_required_and_drafts_rejected(self):
        for overrides in [dict(status='prepared'), dict(receipt_sha256=''), dict(url='http://example.test')]:
            with self.assertRaises(ValueError):
                module.validate([{**self.row(), **overrides}])

    def test_import_is_idempotent_and_preserves_tracker(self):
        changed, count = module.render_import(self.tracker(), [self.row()])
        self.assertEqual(count, 1)
        self.assertNotIn(module.PLACEHOLDER, changed)
        self.assertIn('Keep this content.', changed)
        repeated, count = module.render_import(changed, [self.row()])
        self.assertEqual(count, 0)
        self.assertEqual(repeated, changed)

    def test_table_escape_and_empty_import(self):
        changed, count = module.render_import(self.tracker(), [])
        self.assertEqual(changed, self.tracker())
        row = {**self.row(), 'title': 'Engineer | <script>\ntext'}
        changed, count = module.render_import(self.tracker(), [row])
        self.assertIn('Engineer \\| &lt;script&gt; text', changed)


if __name__ == '__main__':
    unittest.main()
