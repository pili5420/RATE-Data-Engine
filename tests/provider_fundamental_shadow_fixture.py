"""Explicit synthetic engineering material, not real provider company replay."""
from copy import deepcopy
from pathlib import Path

from src.provider_eps_metadata import read_metadata
from src.provider_financial_features import compute_core, seal, consume
from tests.provider_financial_features_fixture import fixture_inputs


def synthetic_inputs(root, create=False, count=24):
    original = fixture_inputs(root, create=create)
    template_eps = [r for r in original["eps"] if r["symbol"] == "2330"]
    template_revenue = [r for r in original["revenue"] if r["symbol"] == "2330"]
    stocks, eps, revenue, gaps = [], [], [], []
    for index in range(count):
        symbol, market = str(1000 + index), "TWSE" if index % 2 else "TPEX"
        stocks.append({"symbol": symbol, "market": market})
        for row in template_eps:
            row = dict(row, symbol=symbol, market=market,
                provider_value=str(index - 12 if row["analysis_quarter"] in ("2025Q3", "2025Q4", "2026Q1", "2026Q2") else -index))
            if index == count - 1 and row["analysis_quarter"] == "2024Q3":
                gaps.append({"symbol": symbol, "market": market, "analysis_quarter": row["analysis_quarter"], "classification": "NO_PROVIDER_ROWS_FOR_QUARTER"})
            else:
                eps.append(row)
        for row in template_revenue:
            row = dict(row, symbol=symbol, market=market, revenue_yoy=str(index // 2 - 6))
            if index == count - 2 and row["period"] == "2026-08":
                row.update(revenue_yoy=None, revenue_yoy_status="UNDEFINED_ZERO_BASE")
            revenue.append(row)
    return {**deepcopy(original), "universe": {"stocks": stocks}, "eps": eps, "revenue": revenue, "gaps": gaps,
        "material_class": "SYNTHETIC_ENGINEERING_ONLY_NOT_REAL_FINANCIAL_REPLAY",
        "source_binding": {"engineering_fixture_root": str(root), "count": count}}


def feature_package(root, count=24):
    return seal(compute_core(synthetic_inputs(root, create=not (Path(root) / "raw").exists(), count=count)),
        code_binding={"base_sha": "0" * 40, "head_sha": "1" * 40})


def load_synthetic(pin):
    directory = Path(pin["synthetic_feature_directory"])
    consume(directory, pin["feature_manifest_sha256"], source_replayer=lambda b: synthetic_inputs(Path(b["engineering_fixture_root"]), count=b["count"]))
    return read_metadata((directory / "PROVIDER_FINANCIAL_FEATURES_V1.json").read_bytes())
