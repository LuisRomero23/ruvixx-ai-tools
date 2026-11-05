import unittest
from datetime import date

from auditor import audit_report


class AuditAcceptanceTests(unittest.TestCase):
    def test_supplied_fixtures_match_expected_findings(self):
        report = audit_report("messy_logs.csv", "active_licenses.csv", date(2026, 11, 4))

        self.assertIn("Rows read: 10; rows dropped as duplicates: 1.", report)
        self.assertIn("Globex Industires -> Globex Industries", report)
        self.assertIn("Line 6 has no valid user email", report)
        self.assertIn("license expired on 2026-09-30; we saw 1 post-expiry event (lines 7)", report)
        self.assertIn("3 different people used the product (frank@starkdyn.com, gina@starkdyn.com, hank@starkdyn.com)", report)
        self.assertIn("Wayne Enterprises has 1 unlicensed activity row (lines 11)", report)
        self.assertIn("Line 11 has an unparseable timestamp. [BAD_TIMESTAMP]", report)
        self.assertIn("Acme Corporation: OK.", report)
        self.assertIn("Umbrella Biotech: OK.", report)
        self.assertIn("We found 7 issues: 3 high, 2 medium, and 2 low severity.", report)


if __name__ == "__main__":
    unittest.main()
