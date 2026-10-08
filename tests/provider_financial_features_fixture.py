"""Synthetic engineering inputs; never a claim of real company/financial replay."""
from pathlib import Path

from src.provider_eps_candidate import build_candidate, WINDOW
from src.provider_financial_features import CONTRACT
from tests.provider_eps_engineering_fixture import make_fixture

VERIFIED = "2026-10-08T14:24:00+00:00"


def fixture_inputs(root, create=True):
    root = Path(root)
    if create:
        make_fixture(root)
    candidate = build_candidate(root, {"base_sha": "0" * 40, "head_sha": "1" * 40})
    eps = [dict(row, verified_observed_at=VERIFIED, market="TPEX" if row["symbol"] == "6488" else "TWSE")
        for c in candidate["companies"] for row in c["quarters"]]
    stocks = [{"symbol": s, "market": "TPEX" if s in {"6488", "7777"} else "TWSE"} for s in ("2330", "1340", "6488", "7777")]
    revenue = [{"symbol": s["symbol"], "market": s["market"], "period": p, "source": "MOPS Official",
        "revenue_yoy": str(index + 1), "revenue_yoy_status": "VALID_NUMERIC", "official_raw_yoy": str(index + 1),
        "observed_at": "2026-10-06T00:00:00+00:00", "source_validated_at": VERIFIED,
        "receipt_reference": "SYNTHETIC_OFFICIAL_REVENUE_NOT_REAL_RECEIPT", "receipt_sha256": "0" * 64,
        "raw_reference": "SYNTHETIC_OFFICIAL_REVENUE_NOT_REAL_RAW", "raw_sha256": "0" * 64,
        "row_identity_locator": {"symbol": s["symbol"], "period": p}}
        for s in stocks for index, p in enumerate(CONTRACT["revenue_months"])]
    return {"material_class": "ENGINEERING_FIXTURE_NOT_REAL_PROVIDER_REPLAY", "universe": {"stocks": stocks},
        "eps": eps, "revenue": revenue, "gaps": [{"symbol": "7777", "market": "TPEX", "analysis_quarter": q,
            "classification": "NO_PROVIDER_ROWS_FOR_QUARTER"} for q in WINDOW],
        "source_binding": {"engineering_fixture_root": str(root), "material_class": "ENGINEERING_FIXTURE_NOT_REAL_PROVIDER_REPLAY"}}
