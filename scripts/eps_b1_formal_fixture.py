"""Fixed engineering inputs through unchanged formal primitives; never persist."""
import copy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(os.environ.get("RATE_B1_FORMAL_CODE_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT))
from src.fundamental import calculate_fundamental
from src.full_replay import replay
from src.production_integration import build_production_bundle, build_production_snapshot
from src.state_chain import deterministic_hash
from scripts.run_rate_0730 import run_rate_0730


def formal_fingerprint():
    eps = [{"symbol": str(1000 + n), "revenue_yoy": [n + 1, n + 2, n + 3],
            "quarterly_eps": [n + 1] * 8} for n in range(30)]
    calculated = calculate_fundamental(copy.deepcopy(eps))
    technical = json.loads((ROOT / "tests/fixtures/technical_replay_30x180.json").read_text(encoding="utf-8"))
    institutional = json.loads((ROOT / "tests/fixtures/institutional_rotation_replay_30.json").read_text(encoding="utf-8"))
    material = replay(technical, institutional)
    validation = {k: "PASS" for k in ("type", "duplicate", "symbol", "trading_date", "freshness",
                  "completeness", "arithmetic", "cross_source", "data_quality")}
    bundle = build_production_bundle(trading_date="2026-09-10", decision_records=material["records"],
                                    provenance={"source": "REPLAY_TEST_ONLY"}, validation=validation)
    snapshot = build_production_snapshot(bundle)
    with patch("scripts.run_rate_0730.append_state", side_effect=AssertionError("PERSIST_FORBIDDEN")):
        decision = run_rate_0730(snapshot, "2026-09-10", "GENESIS_STATE_ID", persist_state=False)
    # Exercise the actual live-source required-history path with no network/write.
    from scripts import build_live_source_bundle as live
    selected = {str(n): {"revenue": {}, "eps": {}} for n in range(30)}
    with patch.object(live, "_accepted_fundamental_history", return_value=None), \
         patch.object(live, "FundamentalHistoryStoreV2") as store, \
         patch.object(live, "MOPSHistoricalFundamentalAdapter") as adapter, \
         patch.object(live, "_write", side_effect=AssertionError("WRITE_FORBIDDEN")):
        store.return_value.select_asof.return_value = selected
        adapter.return_value.fetch_revenue_period.return_value = []
        adapter.return_value.fetch_eps_period.side_effect = RuntimeError("FUNDAMENTAL_EPS_PERIOD_NOT_AVAILABLE:ENGINEERING_FIXTURE")
        try:
            live._fundamental_history(list(selected), as_of_date="2026-10-05")
        except RuntimeError as exc:
            missing_reason = str(exc)
        else:
            raise AssertionError("MISSING_FORMAL_EPS_MUST_NOT_PASS")
        assert not store.return_value.upsert.called
    return {"scope": "ENGINEERING_FIXTURE_ONLY_NO_PRODUCTION_CREDIT",
        "formal_eps_input_sha256": deterministic_hash(eps),
        "fundamental_sha256": deterministic_hash(calculated),
        "scores": {r["symbol"]: {k: r[k] for k in ("rate_composite_score", "short_score", "long_score")}
                   for r in decision["decision"]["records"]},
        "rankings": {k: [r["symbol"] for r in decision[k]] for k in ("top50", "short_top30", "long_top30")},
        "decision_payload": decision["decision"], "state_hash": decision["decision_payload_hash"],
        "state_id": decision["current_state_id"], "missing_formal_eps_gate": missing_reason,
        "state_mutation": 0, "fallback_used": False}


if __name__ == "__main__":
    print(json.dumps(formal_fingerprint(), ensure_ascii=False, sort_keys=True))
