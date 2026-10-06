"""Run-1 regressions; engineering responses grant no Production coverage credit."""
import copy
import json
import os
import subprocess
import unittest
from io import BytesIO
from unittest.mock import patch

from scripts import bootstrap_full_market_history as cli
from src import full_market_history as history
from src.sources.fundamental_history import MOPSHistoricalFundamentalAdapter, MOPS_REVENUE_ARCHIVE, FundamentalHistoryStoreV2
from tests.test_full_market_history import cfg, plan


ENV = {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "100",
       "GITHUB_SHA": "a" * 40, "GITHUB_REPOSITORY": cli.REPOSITORY, "EXECUTION_AUTHORITY": "MAIN_ONLY",
       "GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1"}
RUN = {"id": 100, "head_sha": "a" * 40, "head_branch": "main", "event": "workflow_dispatch", "run_attempt": 1,
       "path": ".github/workflows/rate_full_market_history_bootstrap.yml", "status": "in_progress"}


def authority(response, env=None, *, head=None, ancestry=0):
    def git(_root, *args, **kwargs):
        return subprocess.CompletedProcess(args, ancestry if args[0] == "merge-base" else 0,
                                           (head or "a" * 40) + "\n", "")
    with patch.dict(os.environ, env or ENV, clear=True), patch.object(cli, "git", side_effect=git), \
         patch.object(cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")):
        return cli.main_authority()


def archive_html(month=9, market="TPEX", *, header=True, disclosure=True):
    # Reduced official archive schema, not synthetic Production material.
    # Observed OTC body SHA256: 500e5cbed6b74e88f2e922d8884c7aa9484299408bce6c63e0edebff54d4d284.
    title = ("\u4e0a\u6ac3" if market == "TPEX" else "\u4e0a\u5e02") + "\u516c\u53f8"
    title += f"115\u5e74{month}\u6708\u4efd(\u7d2f\u8a08\u8207\u7576\u6708)\u71df\u696d\u6536\u5165\u7d71\u8a08\u8868"
    return ("<html>" + (f"<font size='5'><b>{title}</b></font>" if header else "")
            + ("<div>\u51fa\u8868\u65e5\u671f\uff1a115/10/06</div>" if disclosure else "")
            + "<table><tr><td><table><tr><th colspan='2'>\u71df\u696d\u6536\u5165</th></tr>"
              "<tr><th>\u516c\u53f8<br>\u4ee3\u865f</th><th>\u516c\u53f8\u540d\u7a31</th>"
              "<th>\u53bb\u5e74\u540c\u6708<br>\u589e\u6e1b(%)</th></tr>"
              "<tr><td>4207</td><td>\u74b0\u6cf0</td><td>14.66</td></tr></table></td></tr></table></html>")


class OfficialArchiveResponse(BytesIO):
    status = 200

    def __init__(self, html, url):
        super().__init__(html.encode("utf-8"))
        self.url = url
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url


def adapter(html, final_url=None):
    def open_response(request, timeout):
        return OfficialArchiveResponse(html, final_url or request.full_url)
    return MOPSHistoricalFundamentalAdapter(opener=open_response, min_interval_seconds=0)


class WarmupRun1DefectTests(unittest.TestCase):
    def test_matrix_api_status_transition_cannot_change_immutable_authority(self):
        identities = []
        for status in ("in_progress", "queued", "pending", "waiting", "requested", "completed", None):
            with self.subTest(status=status):
                response = {**RUN, "status": status}
                identities.append(authority(response))
        response = {**RUN}
        response.pop("status")
        identities.append(authority(response))
        self.assertTrue(all(value == identities[0] for value in identities))

    def test_every_wrong_immutable_github_binding_still_fails_closed(self):
        for field, wrong in (("id", 101), ("head_sha", "b" * 40), ("head_branch", "feature"),
                             ("event", "push"), ("path", ".github/workflows/another.yml"), ("run_attempt", 2)):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "GITHUB_WARMUP_RUN_BINDING_INVALID"):
                authority({**RUN, field: wrong, "status": "queued"})

    def test_runtime_repository_ref_event_checkout_ancestry_and_overrides_remain_strict(self):
        changes = {"GITHUB_ACTIONS": "false", "GITHUB_REPOSITORY": "other/repo", "GITHUB_REF": "refs/heads/feature",
                   "GITHUB_EVENT_NAME": "push", "EXECUTION_AUTHORITY": "LOCAL", "GITHUB_RUN_ID": "101",
                   "GITHUB_RUN_ATTEMPT": "2", "TPEX_HISTORICAL_ENDPOINT": "https://unauthorized.test"}
        for field, wrong in changes.items():
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                authority(RUN, {**ENV, field: wrong})
        with self.assertRaisesRegex(RuntimeError, "WARMUP_SOURCE_COMMIT_MISMATCH"):
            authority(RUN, head="b" * 40)
        with self.assertRaisesRegex(RuntimeError, "WARMUP_COMMIT_NOT_MAIN_ANCESTOR"):
            authority(RUN, ancestry=1)

    def test_official_archive_header_and_exact_final_path_prove_period(self):
        for market in ("TWSE", "TPEX"):
            source = adapter(archive_html(market=market))
            rows = source.fetch_revenue_period(market, "2026-09")
            self.assertEqual(rows[0]["revenue_period"], "2026-09")
            self.assertEqual(rows[0]["official_disclosure_date"], "2026-10-06")
            self.assertEqual(rows[0]["revenue_yoy"], 14.66)
            self.assertEqual(source.diagnostics[-1]["period_identity_source"], "OFFICIAL_ARCHIVE_HEADER_AND_FINAL_PATH")

    def test_official_header_period_mismatch_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_MISMATCH"):
            adapter(archive_html(month=8)).fetch_revenue_period("TPEX", "2026-09")

    def test_missing_header_unproven_path_wrong_market_or_disclosure_fails_closed(self):
        cases = [(archive_html(header=False), None), (archive_html(), "https://unauthorized.test/archive.html"),
                 (archive_html(), MOPS_REVENUE_ARCHIVE.format(market="otc", roc_year=115, month=8)),
                 (archive_html(market="TWSE"), None), (archive_html(disclosure=False), None)]
        for html, url in cases:
            with self.subTest(url=url), self.assertRaises((RuntimeError, ValueError)):
                adapter(html, url).fetch_revenue_period("TPEX", "2026-09")

    def test_comment_or_conflicting_headers_cannot_prove_identity(self):
        title = archive_html().split("<font", 1)[1].split("</font>", 1)[0]
        commented = "<!--<font" + title + "</font>-->" + archive_html(header=False)
        conflicting = archive_html() + archive_html(month=8)
        hidden = archive_html().replace("<b>", "<script>").replace("</b>", "</script>")
        for html in (commented, conflicting, hidden):
            with self.subTest(html=html[:30]), self.assertRaisesRegex(RuntimeError, "FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_UNPROVEN"):
                adapter(html).fetch_revenue_period("TPEX", "2026-09")

    def test_unproven_row_period_cannot_be_substituted_by_valid_header(self):
        html = archive_html().replace("<th>\u516c\u53f8\u540d\u7a31</th>", "<th>\u8cc7\u6599\u5e74\u6708</th>")
        with self.assertRaisesRegex(RuntimeError, "FUNDAMENTAL_REVENUE_PERIOD_IDENTITY_UNPROVEN"):
            adapter(html).fetch_revenue_period("TPEX", "2026-09")

    def test_page_report_date_is_not_backdated_to_requested_month_or_completed_cutoff(self):
        rows = adapter(archive_html()).fetch_revenue_period("TPEX", "2026-09")
        self.assertEqual(rows[0]["official_disclosure_date"], "2026-10-06")
        before = FundamentalHistoryStoreV2.select_asof({"revenue_events": rows, "eps_events": []}, ["4207"], "2026-10-05")
        self.assertEqual(before["4207"]["revenue"], {})
        at_report = FundamentalHistoryStoreV2.select_asof({"revenue_events": rows, "eps_events": []}, ["4207"], "2026-10-06")
        self.assertIn("2026-09", at_report["4207"]["revenue"])

    def test_verified_period_never_authorizes_missing_official_numeric_value(self):
        source = adapter(archive_html().replace("<td>14.66</td>", "<td>--</td>"))
        with self.assertRaisesRegex(ValueError, "FUNDAMENTAL_NUMERIC_MISSING"):
            source.fetch_revenue_period("TPEX", "2026-09")
        self.assertEqual(source.diagnostics[-1]["period_identity_source"], "OFFICIAL_ARCHIVE_HEADER_AND_FINAL_PATH")

    def test_changed_owner_blocks_old_plan_without_plan_hash_bypass(self):
        with patch("src.full_market_history.contract", side_effect=cfg):
            old = copy.deepcopy(plan())
            old["owner_hashes"]["src/sources/fundamental_history.py"] = "27abb9b6514e549257faf5864819ace579b705a19e095028f0b385f13f3d600e"
            old["plan_id"] = "rate-history-plan-" + history.digest({k: v for k, v in old.items() if k != "plan_id"})[:24]
            with self.assertRaisesRegex(RuntimeError, "HISTORY_OWNER_OR_POLICY_MISMATCH"):
                history.validate_plan(old)


if __name__ == "__main__":
    unittest.main()
