"""Synthetic-only R5 semantic and authority boundary regressions."""
import copy
import unittest

from r5_oracle import (Blocked, build, classify_condition, classify_workflow,
                       evaluate_ref_condition, parse, scan_l1)


def source(text):
    import hashlib
    raw = text.encode()
    row = {"path": ".github/workflows/synthetic.yml", "blob": "synthetic",
           "sha256": hashlib.sha256(raw).hexdigest(), "classification": "BLOCKED_RUNTIME_OR_DEPENDENCY",
           "runtime_dependencies": [{"code": "SHELL_EXECUTION_UNVERIFIED"}]}
    return classify_workflow(raw, row)


class R5StaticSemanticTests(unittest.TestCase):
    def test_fixed_runner_simple_command_static_text_only(self):
        row = source("name: t\non: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n")
        self.assertEqual(row["l1_state"], "L1_STATIC_SYNTAX_ONLY")
        self.assertTrue(next(f for f in row["l1_fields"] if f["key"] == "run")["simple_syntax"])
        self.assertEqual(row["l2_state"], "L2_UNQUALIFIED_RUNTIME_EFFECTS")
        self.assertEqual(row["l3_required_check"], "CANDIDATE_UNVERIFIED")

    def test_literal_action_reference_is_not_trusted_execution(self):
        row = source("on: push\njobs:\n  x:\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@v4\n")
        self.assertEqual(row["l1_state"], "L1_STATIC_SYNTAX_ONLY")
        self.assertIn("L1_LITERAL_REFERENCE_ONLY", {f["state"] for f in row["l1_fields"]})
        self.assertEqual(row["l2_state"], "L2_UNQUALIFIED_RUNTIME_EFFECTS")

    def test_ref_predicate_is_deterministic_only_for_push_branch(self):
        for raw in ("github.ref == 'refs/heads/main'", "${{ github.ref == 'refs/heads/main' }}"):
            with self.subTest(raw=raw):
                condition = classify_condition(raw)
                self.assertEqual(condition["state"], "L1_STATIC_REF_PREDICATE")
                self.assertEqual(evaluate_ref_condition(condition, "push", "main"), "TRUE")
                self.assertEqual(evaluate_ref_condition(condition, "push", "other"), "FALSE")
                self.assertEqual(evaluate_ref_condition(condition, "pull_request", "main"), "UNKNOWN")

    def test_workflow_ref_condition_static_syntax_only(self):
        row = source("on: push\njobs:\n  x:\n    if: github.ref == 'refs/heads/main'\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n")
        self.assertEqual(row["l1_state"], "L1_STATIC_SYNTAX_ONLY")
        self.assertEqual(next(f for f in row["l1_fields"] if f["key"] == "if")["state"],
                         "L1_STATIC_REF_PREDICATE")

    def test_dynamic_runner_and_unsupported_condition_fail_closed(self):
        row = source("on: push\njobs:\n  x:\n    if: contains(github.ref, 'main')\n    runs-on: ${{ inputs.runner }}\n    steps:\n      - run: echo ok\n")
        self.assertEqual(row["l1_state"], "L1_PARTIAL_OR_UNRESOLVED")
        self.assertGreaterEqual(row["l1_unresolved_count"], 2)

    def test_secret_env_never_static_verified(self):
        row = source("env:\n  API_KEY: ${{ secrets.API_KEY }}\non: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n")
        self.assertEqual(row["l1_state"], "L1_PARTIAL_OR_UNRESOLVED")
        self.assertIn("L1_CREDENTIAL_VALUE_UNQUALIFIED", {f["state"] for f in row["l1_fields"]})

    def test_reusable_workflow_literal_reference_still_l2_unknown(self):
        row = source("on: push\njobs:\n  x:\n    uses: org/repo/.github/workflows/build.yml@v1\n")
        self.assertTrue(next(f for f in row["l1_fields"] if f["key"] == "uses")["reusable_workflow"])
        self.assertEqual(row["l2_state"], "L2_UNQUALIFIED_RUNTIME_EFFECTS")

    def test_dynamic_action_and_with_input_unresolved(self):
        row = source("on: push\njobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: ${{ inputs.action }}\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}\n")
        self.assertEqual(row["l1_state"], "L1_PARTIAL_OR_UNRESOLVED")

    def test_actual_phase_b_secret_and_live_source(self):
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / ".github/workflows/rate_phase_b_validation.yml"
        raw = path.read_bytes()
        doc = parse(raw)
        fields = scan_l1(doc)
        self.assertTrue(any(f["state"] == "L1_CREDENTIAL_VALUE_UNQUALIFIED" for f in fields))
        self.assertTrue(any(f["key"] == "run" and f["state"] == "L1_LITERAL_COMMAND_TEXT" for f in fields))
        self.assertIn(b"--live", raw)

    def test_duplicate_yaml_key_blocked(self):
        with self.assertRaisesRegex(Blocked, "BLOCKED_DUPLICATE_YAML_KEY"):
            parse(b"on: push\non: pull_request\n")

    def test_wrong_source_hash_blocked(self):
        with self.assertRaisesRegex(Blocked, "BLOCKED_SOURCE_SHA256"):
            classify_workflow(b"on: push", {"sha256": "0" * 64})

    def test_unknown_condition_unqualified(self):
        self.assertEqual(classify_condition("github.event.pull_request.head.sha == 'a'")["state"],
                         "L1_UNRESOLVED_CONDITION")

    def test_ambiguous_owner_or_required_check_cannot_be_promoted(self):
        from pathlib import Path
        baseline = {"source": {"commit": "0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7",
                               "tree": "dbeeb2cc67b43d4d9600b1f7eacee8ba8bdec820",
                               "bundle_sha256": "9fb7afb8292b040b5964085423e15fe360a47bc79cab4ccec989445bcdd286a4"},
                    "workflows": [{"path": f".github/workflows/{i}.yml"} for i in range(156)],
                    "paths": [{"path": f"path/{i}", "owner_authorization": "BLOCKED_UNKNOWN_OWNER",
                               "required_check_configuration": "BLOCKED_UNKNOWN_REQUIRED_CHECK"}
                              for i in range(1055)],
                    "check_candidates": [{"status": "CANDIDATE_UNVERIFIED"} for _ in range(163)]}
        promoted = copy.deepcopy(baseline)
        promoted["paths"][0]["owner_authorization"] = "ASSUMED_OWNER"
        with self.assertRaisesRegex(Blocked, "BLOCKED_OWNER_AUTHORITY_INVENTION"):
            build(promoted, Path("unused"))
        promoted = copy.deepcopy(baseline)
        promoted["check_candidates"][0]["status"] = "ASSUMED_REQUIRED"
        with self.assertRaisesRegex(Blocked, "BLOCKED_CHECK_AUTHORITY_INVENTION"):
            build(promoted, Path("unused"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
