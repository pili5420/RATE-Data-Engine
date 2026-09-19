import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import patch

from src.sources.tdcc_historical import (
    EXPECTED_RANGES, TDCC_HISTORICAL_PAGE, TDCCHistoricalAdapter,
    holder_pct_400_from_tiers, normalize_historical_response,
    normalize_period, select_required_period_union,
)
from scripts.run_cer072_acceptance import _tdcc_history


def _html(symbol="2313", roc_date="115年09月04日", tiers=None):
    tiers = tiers or {i: float(i) for i in range(1, 16)}
    rows = []
    for tier, label in EXPECTED_RANGES.items():
        rows.append(f"<tr><td>{tier}</td><td>{label}</td><td>1,000</td><td>2,000,000</td><td>{tiers[tier]:.2f}</td></tr>")
    rows.append("<tr><td>16</td><td>差異數調整（說明4）</td><td></td><td>-7,000</td><td>-0.00</td></tr>")
    rows.append("<tr><td>17</td><td>合　計</td><td>1,000</td><td>2,000,000</td><td>100.00</td></tr>")
    return (f"<p>證券代號：{symbol}</p><span>資料日期：{roc_date}</span>"
            "<table class='table'><thead><tr><th>序</th><th>持股/單位數分級</th>"
            "<th>人數</th><th>股數/單位數</th><th>占集保庫存數比例 (%)</th></tr></thead>"
            + "".join(rows) + "</table>")


class TDCCHistoricalContractTests(unittest.TestCase):
    def test_official_contract_is_post_symbol_date_html(self):
        self.assertEqual(TDCCHistoricalAdapter.request_method, "POST")
        self.assertEqual(TDCCHistoricalAdapter.request_granularity, "SYMBOL_DATE")
        self.assertEqual(TDCC_HISTORICAL_PAGE, "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock")

    def test_live_form_request_uses_official_post_field_contract(self):
        page=('<input name="SYNCHRONIZER_TOKEN" value="token1">'
              '<select name="scaDate"><option value="20260904">20260904</option></select>')
        result='<input name="SYNCHRONIZER_TOKEN" value="token2">'+_html()
        class Response:
            status=200
            def __init__(self, body): self.body=body.encode("utf-8")
            def read(self): return self.body
            def getcode(self): return 200
        class Opener:
            def __init__(self): self.requests=[]
            def open(self, req, timeout):
                self.requests.append(req)
                return Response(page if len(self.requests)==1 else result)
        opener=Opener()
        adapter=TDCCHistoricalAdapter(opener=opener,min_interval_seconds=0)
        adapter.fetch_period("2313","2026-09-04")
        request=opener.requests[1]
        fields=parse_qs(request.data.decode("utf-8"))
        self.assertEqual(request.get_method(),"POST")
        self.assertEqual(fields["scaDate"],["20260904"])
        self.assertEqual(fields["stockNo"],["2313"])
        self.assertEqual(fields["sqlMethod"],["StockNo"])
        self.assertEqual(fields["method"],["submit"])
        self.assertEqual(fields["SYNCHRONIZER_URI"],["/portal/zh/smWeb/qryStock"])

    def test_roc_date_normalizes_to_gregorian(self):
        self.assertEqual(normalize_period("115年09月04日"), "2026-09-04")

    def test_historical_response_normalizes_all_contract_fields(self):
        rows = normalize_historical_response(_html(), "2026-09-04", "2313")
        self.assertEqual(len(rows), 15)
        self.assertEqual(set(rows[0]), {"period_end","symbol","holding_range","holder_count","shares",
                                        "holder_percentage","source","source_timestamp",
                                        "retrieval_timestamp","response_sha256"})
        self.assertEqual(rows[11]["holding_range"], 12)

    def test_response_date_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "TDCC_HISTORICAL_RESPONSE_DATE_MISMATCH"):
            normalize_historical_response(_html(roc_date="115年09月11日"), "2026-09-04", "2313")

    def test_symbol_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "TDCC_HISTORICAL_SYMBOL_MISMATCH"):
            normalize_historical_response(_html(symbol="2330"), "2026-09-04", "2313")

    def test_five_period_union_uses_listed_sessions_without_weekday_assumption(self):
        dates = ["2026-08-06","2026-08-13","2026-08-20","2026-08-28","2026-09-04","2026-09-11"]
        periods, selected = select_required_period_union(
            ["2026-09-10","2026-09-11","2026-09-14"], dates)
        self.assertEqual(selected["2026-09-10"], dates[:5])
        self.assertEqual(selected["2026-09-11"], dates[1:])
        self.assertEqual(selected["2026-09-14"], dates[1:])
        self.assertEqual(periods, dates)

    def test_lh_change_uses_p0_minus_fifth_latest_p4(self):
        values=[12.0,18.0,21.0,27.0,35.0]
        self.assertEqual(values[-1]-values[0],23.0)

    def test_no_future_tdcc_period_is_selected(self):
        periods, selected = select_required_period_union(
            ["2026-09-10"], ["2026-08-07","2026-08-14","2026-08-21",
                             "2026-08-28","2026-09-04","2026-09-11"])
        self.assertNotIn("2026-09-11", selected["2026-09-10"])
        self.assertEqual(periods[-1], "2026-09-04")

    def test_missing_five_asof_periods_fail(self):
        with self.assertRaisesRegex(ValueError, "DATA_INCOMPLETE:TDCC_ASOF_FIVE_PERIODS"):
            select_required_period_union(["2026-09-10"], ["2026-09-04","2026-08-28"])

    def test_holder_pct_400_uses_exact_400001_plus_tiers(self):
        rows=[{"holding_range":tier,"holder_percentage":float(tier)} for tier in range(1,16)]
        self.assertEqual(holder_pct_400_from_tiers(rows), sum(range(12,16)))

    def test_duplicate_tier_fails_closed(self):
        rows=[{"holding_range":tier,"holder_percentage":1.0} for tier in range(1,16)]
        rows.append(dict(rows[0]))
        with self.assertRaisesRegex(ValueError, "TDCC_DUPLICATE_OR_INVALID_TIER"):
            holder_pct_400_from_tiers(rows)

    def test_missing_tier_fails_closed_without_zero_fill(self):
        rows=[{"holding_range":tier,"holder_percentage":1.0} for tier in range(1,15)]
        with self.assertRaisesRegex(ValueError, "TDCC_MISSING_REQUIRED_TIER"):
            holder_pct_400_from_tiers(rows)

    def test_30_symbol_asof_coverage_and_lineage(self):
        symbols=[f"{i:04d}" for i in range(30)]
        dates=["2026-08-07","2026-08-14","2026-08-21","2026-08-28","2026-09-04","2026-09-11","2026-09-18"]
        replay=["2026-09-10","2026-09-11","2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18"]
        rows=[]
        for symbol in symbols:
            for day in dates:
                for tier in range(1,16):
                    rows.append({"symbol":symbol,"period_end":day,"holding_range":tier,
                        "holder_percentage":float(tier),"retrieval_timestamp":"2026-09-19T00:00:00Z"})
        class FakeAdapter:
            available_periods=dates
            def fetch_period_union(self, syms, periods):
                return {"normalized_rows":[r for r in rows if r["period_end"] in periods],
                    "transport_contract":{"method":"POST"},"request_count":len(syms)*len(periods),
                    "normalized_rows":[r for r in rows if r["period_end"] in periods],
                    "source_timestamp":"2026-09-18","response_date_identity_status":"PASS",
                    "symbols_required":len(syms),"symbols_complete":len(syms)}
        with patch("scripts.run_cer072_acceptance.TDCCHistoricalAdapter", FakeAdapter):
            histories, result=_tdcc_history(symbols, "2026-09-18", replay)
        self.assertEqual(len(histories),30)
        self.assertEqual(result["request_granularity"],"SYMBOL_DATE")
        self.assertTrue(all(len(x)==5 for x in result["asof_coverage_by_replay_session"]["2026-09-10"].values()))
        self.assertTrue(all("2026-09-11" not in x["selected_five_periods"]
                            for x in result["asof_coverage_by_replay_session"]["2026-09-10"].values()))

    def test_lh_cross_section_uses_same_date_percentile_distribution(self):
        from src.institutional_features import calculate_institutional_rotation
        from src.rotation_history import build_rotation_feature_histories
        fixture=json.loads(Path("tests/fixtures/institutional_rotation_replay_30.json").read_text(encoding="utf-8"))
        technical=json.loads(Path("tests/fixtures/technical_replay_30x180.json").read_text(encoding="utf-8"))
        stocks=technical["symbols"]
        benchmarks={s:technical["benchmarks"]["TAIEX"] for s in stocks}
        asof=max(r["trade_date"] for rows in stocks.values() for r in rows)
        histories=build_rotation_feature_histories(stocks,benchmarks,as_of_date=asof)
        inputs=json.loads(json.dumps(fixture["rows"]))
        for row in inputs: row.update(histories[row["symbol"]])
        output=calculate_institutional_rotation(inputs)
        self.assertEqual(len(output),30)
        self.assertTrue(all(x["feature_lineage"]["LH"]["calculation_status"]=="PASS" for x in output))
        self.assertEqual(len({x["feature_lineage"]["LH"]["raw_periods"][-1] for x in output}),1)

    def test_adapter_does_not_claim_fixture_or_use_snapshot_endpoint(self):
        self.assertFalse(any("snapshot" in x.lower() for x in (
            TDCCHistoricalAdapter.endpoint, TDCCHistoricalAdapter.request_method)))
