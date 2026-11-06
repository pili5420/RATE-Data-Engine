"""Offline positive and adversarial checks for design-only gate."""
import unittest

from scripts.verify_rate_design_only_ci import (
    DESIGN_FILES, GATE_FILES, DesignGateError, validate_scope,
)

BASE = "a" * 40
HEAD = "b" * 40
B_DOC = """## Problem, source custody and non-credit boundary
## Proposed future new-boundary contract
## Contract-gap matrix
## Offline regression / proof specification
### Owner decisions remaining
B01: check; B10: check; POST_REBASELINE_ONLY; NO_AUTO_NEXT=TRUE
"""
C_DOC = """## Current immutable authority and observed failure
## Options and recommendation
## Proposed offline architecture
## Contract change impact
## Offline simulated PoC test vectors
### Owner decisions required
C01 and C12; 900; event=schedule; NO_AUTO_NEXT=TRUE
"""


class DesignGateTests(unittest.TestCase):
    def check(self, number, changed, doc):
        return validate_scope(number=number, base_sha=BASE, head_sha=HEAD,
                              changed=changed, document=doc)

    def test_b_document_only(self):
        self.assertEqual(self.check(213, [DESIGN_FILES[213]], B_DOC)
                         ["validation_mode"], "DESIGN_DOC_ONLY")

    def test_c_document_only(self):
        self.assertEqual(self.check(214, [DESIGN_FILES[214]], C_DOC)
                         ["validation_mode"], "DESIGN_DOC_ONLY")

    def test_gate_self_scope(self):
        self.assertEqual(self.check(999, sorted(GATE_FILES), None)
                         ["validation_mode"], "GATE_SELF_REVIEW_ONLY")

    def test_reject_wrong_design(self):
        with self.assertRaises(DesignGateError):
            self.check(213, [DESIGN_FILES[214]], B_DOC)

    def test_reject_scope_expansion(self):
        for path in ("config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json",
                     "artifacts/RATE_PRODUCTION_STATE_LATEST.json",
                     "src/production_acceptance_session.py",
                     ".github/workflows/rate_production_1930_scheduler.yml"):
            with self.subTest(path=path), self.assertRaises(DesignGateError):
                self.check(213, [DESIGN_FILES[213], path], B_DOC)

    def test_reject_missing_section(self):
        with self.assertRaises(DesignGateError):
            self.check(214, [DESIGN_FILES[214]], C_DOC.replace("## Contract change impact", ""))

    def test_reject_unknown_doc_pr(self):
        with self.assertRaises(DesignGateError):
            self.check(215, [DESIGN_FILES[213]], B_DOC)

    def test_reject_partial_self_review(self):
        with self.assertRaises(DesignGateError):
            self.check(999, ["scripts/verify_rate_design_only_ci.py"], None)

    def test_reject_duplicate_changes(self):
        with self.assertRaises(DesignGateError):
            self.check(213, [DESIGN_FILES[213], DESIGN_FILES[213]], B_DOC)

    def test_reject_invalid_sha(self):
        with self.assertRaises(DesignGateError):
            validate_scope(number=213, base_sha="bad", head_sha=HEAD,
                           changed=[DESIGN_FILES[213]], document=B_DOC)


if __name__ == "__main__":
    unittest.main()
