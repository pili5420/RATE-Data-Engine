"""Synthetic acceptance only; no live requests or provider authorization."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlencode

from src.eps_duration_facts.model import Rejected
from src.eps_duration_facts.raw import sha256
from src.full_market_history import put_bytes
from src.provider_eps_candidate import API, WINDOW, _canonical
from src.provider_eps_dispatch import exclusive_scan
from src.provider_eps_metadata import read_metadata
from src.provider_revenue_snapshot import endpoint
from src.sources.mops_raw_evidence import NORMALIZATION_VERSION
from src.prospective_fundamental_provider import (CONTRACT, ROOT, append, exact_date, inspect_source,
    issuer_readiness, new_store, parser_identity, prospective_record, replay, review_decision)
from tests.test_provider_revenue_snapshot import html

ACTIVATION = "2026-10-10T00:00:00+00:00"
REQUESTED = "2026-10-10T00:00:01+00:00"
RECEIVED = "2026-10-10T00:00:02+00:00"
VALIDATED = "2026-10-10T00:00:03+00:00"
LATER = "2026-10-10T00:00:04+00:00"
EXECUTION = {"base_sha": CONTRACT["base_sha"], "head_sha": "a" * 40}


def universe():
    return {"verification_status": "PASS", "catalogue_id": "SYNTHETIC_EXACT_UNIVERSE_NOT_REAL",
        "stocks": [{"symbol": str(1000 + n), "market": "TWSE" if n < 1085 else "TPEX"} for n in range(1978)]}


def eps(rows=None, **changes):
    if rows is None:
        rows = [{"stock_id": "1000", "date": exact_date(q), "type": "EPS", "origin_name": "基本每股盈餘",
                 "value": "-0.123456789012345678901" if i == 0 else "0"} for i, q in enumerate(WINDOW)]
    raw = json.dumps({"status": 200, "data": rows}, ensure_ascii=False, allow_nan=False).encode()
    query = {"dataset": "TaiwanStockFinancialStatements", "data_id": "1000", "start_date": "2024-07-01", "end_date": "2026-06-30"}
    receipt = {"query": query, "requested_url": API, "final_url": API + "?" + urlencode(query),
        "attempts": 1, "started_at": REQUESTED, "received_at": RECEIVED, "finished_at": VALIDATED,
        "http_status": 200, "bytes": len(raw), "content_length": len(raw), "response_body_sha256": sha256(raw),
        "fallback_used": False, **changes}
    return raw, receipt


def revenue(period="2026-07", rows=None, **changes):
    raw = html("TWSE", period, [("1000", "1.23456789012345")] if rows is None else rows)
    receipt = {"source_owner": "MOPS Official", "domain": "revenue", "market": "TWSE", "requested_period": period,
        "endpoint": endpoint("TWSE", period), "final_url": endpoint("TWSE", period), "normalization_version": NORMALIZATION_VERSION,
        "parser_sha256": parser_identity("MOPS Official")["sha256"], "request_started_at": REQUESTED,
        "retrieval_timestamp": RECEIVED, "body_sha256": sha256(raw), "response_bytes": len(raw), "content_length": len(raw),
        "http_status": 200, "fallback_used": False, "official_report_disclosure_date": "2026-10-09", **changes}
    return raw, receipt


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="prospective-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "evidence"
        self.universe = universe()
        self.pin = new_store(self.root, self.universe, EXECUTION, ACTIVATION)

    def inspect(self, data=None, provider="FinMind", target=None, validated=VALIDATED, **kw):
        raw, receipt = data or eps()
        body = _canonical(receipt)
        return inspect_source(provider, target or {"symbol": "1000", "market": "TWSE"}, raw, body,
            sha256(raw), sha256(body), self.universe, validated, **kw)

    def add(self, data=None, head=None, provider="FinMind", target=None, now=LATER):
        raw, receipt = data or eps()
        return append(self.root, self.pin, head, provider, target or {"symbol": "1000", "market": "TWSE"},
            raw, _canonical(receipt), ACTIVATION, now)

    def test_identity_eps_pass(self):
        inspected = self.inspect()
        self.assertEqual(inspected["source_identity_gate"], "PASS")
        self.assertIsNone(inspected["source_parser_sha256"])
        self.assertEqual(inspected["parser_version"], parser_identity("FinMind"))

    def test_identity_mops_pass(self):
        value = self.inspect(revenue(), "MOPS Official", {"market": "TWSE", "period": "2026-07"})
        self.assertEqual(value["source_identity_gate"], "PASS")
        self.assertEqual(value["rows"][0]["json_locator"], {"market":"TWSE","symbol":"1000","period":"2026-07","parsed_row_index_zero_based":0})

    def test_endpoint_mismatch(self):
        with self.assertRaises(Rejected): self.inspect(eps(requested_url="https://example.org"))

    def test_https_required(self):
        with self.assertRaises(Rejected): self.inspect(eps(final_url=API.replace("https", "http")))

    def test_dataset_mismatch(self):
        raw, r = eps(); r["query"]["dataset"] = "Other"
        with self.assertRaises(Rejected): self.inspect((raw, r))

    def test_symbol_mismatch(self):
        with self.assertRaises(Rejected): self.inspect(target={"symbol": "1001", "market": "TWSE"})

    def test_market_mismatch(self):
        with self.assertRaises(Rejected): self.inspect(target={"symbol": "1000", "market": "TPEX"})

    def test_http_failure(self):
        with self.assertRaises(Rejected): self.inspect(eps(http_status=403))

    def test_redirect_rejected(self):
        with self.assertRaises(Rejected): self.inspect(eps(final_url=API + "/redirect"))

    def test_retries_rejected(self):
        with self.assertRaises(Rejected): self.inspect(eps(attempts=2))

    def test_fallback_rejected(self):
        with self.assertRaises(Rejected): self.inspect(eps(fallback_used=True))

    def test_raw_tamper(self):
        raw, r = eps()
        with self.assertRaises(Rejected): inspect_source("FinMind", {"symbol": "1000", "market": "TWSE"}, raw+b" ", _canonical(r), sha256(raw), sha256(_canonical(r)), self.universe, VALIDATED)

    def test_receipt_tamper(self):
        raw, r = eps(); body = _canonical(r)
        with self.assertRaises(Rejected): inspect_source("FinMind", {"symbol": "1000", "market": "TWSE"}, raw, body+b" ", sha256(raw), sha256(body), self.universe, VALIDATED)

    def test_receipt_body_binding(self):
        with self.assertRaises(Rejected): self.inspect(eps(response_body_sha256="0"*64))

    def test_future_time(self):
        with self.assertRaises(Rejected): self.inspect(eps(received_at="2999-01-01T00:00:00Z"))

    def test_pre_activation_rejected(self):
        with self.assertRaises(Rejected): prospective_record(self.inspect(), "2026-10-10T00:00:02Z", LATER)

    def test_request_not_inferred_from_received(self):
        i = self.inspect(revenue(request_started_at=None), "MOPS Official", {"market": "TWSE", "period": "2026-07"})
        with self.assertRaisesRegex(Rejected, "REQUEST_TIME_NOT_EVIDENCED"): prospective_record(i, ACTIVATION, LATER)

    def test_first_seen_not_publication(self):
        r = prospective_record(self.inspect(), ACTIVATION, LATER)
        self.assertEqual(r["first_seen_at"], LATER)
        self.assertIsNone(r["original_publication_timestamp"])
        self.assertEqual(r["historical_pit"], "UNPROVEN")

    def test_publication_claim_rejected(self):
        with self.assertRaises(Rejected): self.inspect(eps(original_publication_timestamp=RECEIVED))

    def test_pit_promotion_rejected(self):
        i = self.inspect(); i["historical_pit"] = "PASS"
        with self.assertRaises(Rejected): prospective_record(i, ACTIVATION, LATER)

    def test_nonquarter_end_rejected(self):
        raw, _ = eps(); rows = json.loads(raw)["data"]; rows[0]["date"] = "2024-09-29"
        with self.assertRaises(Rejected): self.inspect(eps(rows))

    def test_duplicate_quarter_rejected(self):
        raw, _ = eps(); rows = json.loads(raw)["data"]; rows.append(rows[0])
        with self.assertRaises(Rejected): self.inspect(eps(rows))

    def test_conflicting_quarter_rejected(self):
        raw, _ = eps(); rows = json.loads(raw)["data"]; rows.append(dict(rows[0], value="99"))
        with self.assertRaises(Rejected): self.inspect(eps(rows))

    def test_fuzzy_label_rejected(self):
        raw, _ = eps(); rows = json.loads(raw)["data"]; rows[0]["origin_name"] = "基本每股盈餘 extra"
        with self.assertRaises(Rejected): self.inspect(eps(rows))

    def test_nonfinite_rejected(self):
        raw, _ = eps(); rows = json.loads(raw)["data"]
        for value in ("NaN", "Infinity", True):
            with self.subTest(value=value):
                rows[0]["value"] = value
                with self.assertRaises(Rejected): self.inspect(eps(rows))

    def test_decimal_negative_zero_preserved(self):
        r = self.inspect()["rows"]
        self.assertEqual(Decimal(r[0]["value"]), Decimal("-0.123456789012345678901"))
        self.assertEqual(r[1]["value"], "0")

    def test_missing_period_preserves_valid_rows(self):
        raw, _ = eps(); rows = json.loads(raw)["data"][:-1]
        head = self.add(eps(rows)); config, events = replay(self.root, self.pin, head, LATER)
        row = issuer_readiness(config, events)[0]
        self.assertEqual(len(row["valid_partial_periods"]), 7)
        self.assertEqual(row["missing_reasons"]["FinMind"], [{"period": "2026Q2", "reason": "MISSING_REQUIRED_PERIOD"}])

    def test_no_zero_fill_all_issuers_retained(self):
        config, events = replay(self.root, self.pin, None, LATER)
        rows = issuer_readiness(config, events)
        self.assertEqual(len(rows), 1978)
        self.assertTrue(all(r["valid_partial_periods"] == [] and r["fundamental_input_status"] == "NOT_READY_MISSING_REQUIRED_PERIOD" for r in rows))

    def test_all_required_periods_ready_no_ranking(self):
        head = self.add()
        for period in CONTRACT["required_periods"]["REVENUE"]:
            head = self.add(revenue(period), head, "MOPS Official", {"market": "TWSE", "period": period})
        config, events = replay(self.root, self.pin, head, LATER)
        rows = issuer_readiness(config, events)
        self.assertEqual(rows[0]["fundamental_input_status"], "READY")
        self.assertFalse(rows[0]["ranking_eligible"])
        self.assertEqual(len(rows), 1978)

    def test_zero_base_not_zero(self):
        head = self.add(revenue(rows=[("1000", None)]), provider="MOPS Official", target={"market": "TWSE", "period": "2026-07"})
        config, events = replay(self.root, self.pin, head, LATER)
        row = issuer_readiness(config, events)[0]
        self.assertIsNone(row["valid_partial_periods"][0]["value"])
        self.assertEqual(row["missing_reasons"]["MOPS Official"][0]["reason"], "UNDEFINED_ZERO_BASE")

    def test_revision_chain_preserves_prior(self):
        head = self.add(); before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file() and p.name != ".scan.lock"}
        raw, _ = eps(); rows = json.loads(raw)["data"]; rows[0]["value"] = "7"
        new = self.add(eps(rows, received_at=VALIDATED, finished_at=LATER), head)
        config, events = replay(self.root, self.pin, new, LATER)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["previous_scope_observation"], events[0]["record"]["immutable_snapshot_id"])
        self.assertTrue(all(Path(p).read_bytes() == b for p,b in before.items()))
        self.assertNotEqual(events[0]["record"]["rows"][0]["value"], issuer_readiness(config, events)[0]["valid_partial_periods"][0]["value"])

    def test_removed_row_not_backfilled(self):
        head = self.add(); raw, _ = eps(); rows = json.loads(raw)["data"][:-1]
        head = self.add(eps(rows, received_at=VALIDATED, finished_at=LATER), head)
        c, e = replay(self.root, self.pin, head, LATER)
        self.assertEqual(issuer_readiness(c,e)[0]["eps_status"], "NOT_READY_MISSING_REQUIRED_PERIOD")

    def test_duplicate_observation_rejected(self):
        head = self.add()
        with self.assertRaises(Rejected): self.add(head=head)

    def test_stale_head_rejected(self):
        self.add()
        with self.assertRaises(Rejected): self.add()

    def test_overwrite_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "IMMUTABLE_HISTORY_CONFLICT"): put_bytes(self.root, "SANDBOX.json", b"changed")

    def test_event_mutation_rejected(self):
        head = self.add(); path = next((self.root/"events").iterdir()); path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaises(Rejected): replay(self.root, self.pin, head, LATER)

    def test_ledger_truncation_rejected(self):
        head = self.add(); next((self.root/"events").iterdir()).unlink()
        with self.assertRaises(Rejected): replay(self.root, self.pin, head, LATER)

    def test_raw_disk_mutation_rejected(self):
        head = self.add(); next((self.root/"raw").iterdir()).write_bytes(b"changed")
        with self.assertRaises(Rejected): replay(self.root, self.pin, head, LATER)

    def test_receipt_disk_mutation_rejected(self):
        head = self.add(); next((self.root/"receipts").iterdir()).write_bytes(b"changed")
        with self.assertRaises(Rejected): replay(self.root, self.pin, head, LATER)

    def test_config_mutation_rejected(self):
        (self.root/"SANDBOX.json").write_bytes(b"{}")
        with self.assertRaises(Rejected): replay(self.root, self.pin, None, LATER)

    def test_wrong_exact_head_format(self):
        with self.assertRaises(Rejected): new_store(Path(self.temp.name)/"other", self.universe, dict(EXECUTION,head_sha="bad"), ACTIVATION)

    def test_exact_universe_required(self):
        u = deepcopy(self.universe); u["stocks"].pop()
        with self.assertRaises(Rejected): new_store(Path(self.temp.name)/"other", u, EXECUTION, ACTIVATION)

    def test_activation_binding_cannot_change(self):
        raw, r = eps()
        with self.assertRaises(Rejected): append(self.root,self.pin,None,"FinMind",{"symbol":"1000","market":"TWSE"},raw,_canonical(r),REQUESTED,LATER)

    def test_second_writer_rejected(self):
        with exclusive_scan(self.root):
            with self.assertRaisesRegex(RuntimeError, "COVERAGE_WRITER_ALREADY_ACTIVE"): self.add()

    def test_protected_output_rejected(self):
        with self.assertRaises(Rejected): new_store(Path(self.temp.name)/"Production"/"fresh",self.universe,EXECUTION,ACTIVATION)

    def test_source_parser_pin_not_changed(self):
        owner = (ROOT/parser_identity("MOPS Official")["owner"]).read_bytes()
        old = owner.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n")
        i = self.inspect(revenue(parser_sha256=sha256(old)),"MOPS Official",{"market":"TWSE","period":"2026-07"},original_parser_bytes=old)
        self.assertEqual(i["source_parser_sha256"],sha256(old))
        with self.assertRaises(Rejected): self.inspect(revenue(parser_sha256=sha256(old+b"#change")),"MOPS Official",{"market":"TWSE","period":"2026-07"},original_parser_bytes=old+b"#change")

    def test_provider_authorization_independent_of_completeness(self):
        d = review_decision({"FinMind":"PASS","MOPS Official":"PASS"},True)
        self.assertEqual(d["gate_a7"],"READY_FOR_PROSPECTIVE_PROVIDER_ACTIVATION_REVIEW")
        self.assertTrue(all(p["proposed_authorization"]=="AUTHORIZED" and p["provider_authorization"]=="NOT_AUTHORIZED" for p in d["providers"]))

    def test_source_fail_blocks_review(self):
        self.assertEqual(review_decision({"FinMind":"FAIL","MOPS Official":"PASS"},True)["gate_a7"],"BLOCKED")

    def test_engineering_fail_blocks_review(self):
        self.assertEqual(review_decision({"FinMind":"PASS","MOPS Official":"PASS"},False)["gate_a7"],"BLOCKED")

    def test_cold_process_replay(self):
        head = self.add()
        for n in range(2):
            output = Path(self.temp.name)/f"cold-{n}.json"
            run = subprocess.run([sys.executable,"-B",str(ROOT/"scripts/run_prospective_provider_acceptance.py"),
                "--replay-sandbox",str(self.root),"--config-sha256",self.pin,"--trusted-head",head,
                "--as-of",LATER,"--output-file",str(output)],capture_output=True,text=True,encoding="utf-8")
            self.assertEqual(run.returncode,0,run.stderr)
            proof = read_metadata(output.read_bytes())
            self.assertEqual(proof["ledger_head"],head)
            self.assertEqual(proof["events"],1)
        self.assertEqual(len(list((self.root/"events").iterdir())),1)

    def test_existing_owners_do_not_import_candidate(self):
        for path in (ROOT/"src").rglob("*.py"):
            if path.name != "prospective_fundamental_provider.py":
                self.assertNotIn("import prospective_fundamental_provider",path.read_text(encoding="utf-8"))
                self.assertNotIn("from .prospective_fundamental_provider",path.read_text(encoding="utf-8"))

    def test_governance_not_activated(self):
        self.assertIsNone(CONTRACT["activation_timestamp"])
        for key in ("production_eligible","decision_eligible","fallback_allowed"):
            self.assertIs(CONTRACT[key],False)
        self.assertEqual(CONTRACT["provider_authorization"],"NOT_AUTHORIZED")
        self.assertEqual(CONTRACT["external_authorized_intraday_feed_dependency"],"BLOCKED_EXTERNAL")

    def test_wrong_provider_rejected(self):
        with self.assertRaises(Rejected): self.inspect(provider="Other")

    def test_revenue_wrong_month_rejected(self):
        with self.assertRaises(Rejected): self.inspect(revenue(),"MOPS Official",{"market":"TWSE","period":"2026-08"})

    def test_revenue_wrong_market_rejected(self):
        with self.assertRaises(Rejected): self.inspect(revenue(),"MOPS Official",{"market":"TPEX","period":"2026-07"})

    def test_first_seen_cannot_predate_validation(self):
        with self.assertRaises(Rejected): prospective_record(self.inspect(),ACTIVATION,RECEIVED)

    def test_future_first_seen_rejected(self):
        with self.assertRaises(Rejected): prospective_record(self.inspect(),ACTIVATION,"2999-01-01T00:00:00Z")

    def test_no_old_period_substitution(self):
        raw,_ = eps(); rows = json.loads(raw)["data"]; rows[0]["date"] = "2024-06-30"
        with self.assertRaises(Rejected): self.inspect(eps(rows))

    def test_write_guard_protects_state_portfolio_ledger_ranking(self):
        from scripts.run_prospective_provider_acceptance import guard
        audit = guard(self.root)
        for name in ("Production/LATEST","Decision State","Roy Portfolio","AI Paper Portfolio","Transaction Ledger","ranking.json"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError,"WRITE_OUTSIDE_FRESH_OUTPUT"):
                    audit("open",(str(Path(self.temp.name)/name),"w",0))

    def test_network_guard_no_financial_requests(self):
        from scripts.run_prospective_provider_acceptance import guard
        for event in ("socket.connect","socket.getaddrinfo","socket.sendto"):
            with self.assertRaisesRegex(RuntimeError,"NETWORK_FORBIDDEN"): guard(self.root)(event,())

    def test_cli_exact_head_mismatch_rejected(self):
        binding = Path(self.temp.name)/"binding.json"
        binding.write_bytes(_canonical({"execution":dict(EXECUTION,head_sha="0"*40)}))
        output = Path(self.temp.name)/"rejected"
        run = subprocess.run([sys.executable,"-B",str(ROOT/"scripts/run_prospective_provider_acceptance.py"),
            "--binding",str(binding),"--binding-sha256",sha256(binding.read_bytes()),"--output-dir",str(output)],
            capture_output=True,text=True,encoding="utf-8")
        self.assertNotEqual(run.returncode,0)
        self.assertIn("PROSPECTIVE_EXACT_HEAD_MISMATCH",run.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
