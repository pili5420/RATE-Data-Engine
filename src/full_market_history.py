"""Content-addressed history SSOT. No production state or ranking publication."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from .full_market_catalogue import policy_hash, validate_catalogue
from .production_live_state import require

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/RATE_FULL_MARKET_HISTORY_BOOTSTRAP_V1.json"
OWNER_FILES = (
    "src/historical_store.py", "src/sources/twse.py", "src/sources/tpex.py",
    "src/sources/tdcc_historical.py", "src/sources/fundamental_history.py",
    "src/institutional_history.py", "src/institutional_features.py", "src/stage_history.py",
    "src/rotation_history.py", "src/technical_features.py", "src/rate_logic.py",
    "src/feature_math.py", "src/sources/base.py", "src/sources/tpex_transport.py",
    "src/cer080_multi_day_continuity.py", "scripts/resolve_production_runtime_context.py",
    "scripts/materialize_production_history_store.py", "scripts/build_live_source_bundle.py",
)
DOMAINS = ("stock", "benchmark", "institutional", "tdcc", "fundamental")


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def contract():
    value = json.loads(CONTRACT.read_bytes())
    require(value["policy_hash"] == policy_hash() and value["fallback_allowed"] is False,
            "WARMUP_POLICY_BINDING_INVALID")
    return value


def owners():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in OWNER_FILES}


def eligible(catalogue):
    rows = [r for m in catalogue["markets"] for r in m["records"] if r["eligible"]]
    symbols = [r["symbol"] for r in rows]
    require(all(isinstance(s, str) and s and "/" not in s and "\\" not in s and s not in (".", "..") for s in symbols),
            "OFFICIAL_SYMBOL_PATH_INVALID")
    require(len(symbols) == len(set(symbols)), "DUPLICATE_SYMBOL")
    counts = dict(Counter(r["market"] for r in rows))
    require(counts == contract()["expected_market_counts"], "CATALOGUE_COUNT_CHANGE_REQUEST_REQUIRED")
    return sorted(rows, key=lambda r: (r["market"], r["symbol"]))


def validate_authority(value):
    require(value.get("ref") == "refs/heads/main" and value.get("event") == "workflow_dispatch"
            and str(value.get("run_id", "")).isdigit()
            and ("run_attempt" not in value or str(value["run_attempt"]).isdigit() and int(value["run_attempt"]) >= 1)
            and len(value.get("commit_sha", "")) == 40
            and all(c in "0123456789abcdef" for c in value["commit_sha"]), "WARMUP_MAIN_AUTHORITY_REQUIRED")
    evidence = value.get("github_execution_evidence", {})
    require(evidence.get("run_id") == str(value["run_id"]) and evidence.get("head_sha") == value["commit_sha"]
            and evidence.get("head_branch") == "main" and evidence.get("event") == "workflow_dispatch"
            and evidence.get("workflow_path") == ".github/workflows/rate_full_market_history_bootstrap.yml"
            and evidence.get("run_attempt") == str(value.get("run_attempt", "1")), "GITHUB_WARMUP_RUN_BINDING_INVALID")


def build_plan(catalogue, authority):
    validate_authority(authority)
    validate_catalogue(catalogue, catalogue["as_of"])
    rows = eligible(catalogue)
    from scripts.resolve_production_runtime_context import _previous_legal_trading_day
    completed = _previous_legal_trading_day(catalogue["as_of"])
    from scripts.resolve_production_runtime_context import _today_taipei
    require(catalogue["as_of"] <= _today_taipei(), "FUTURE_ASOF")
    shards = []
    size = contract()["symbols_per_shard"]
    for market in ("TWSE", "TPEX"):
        symbols = sorted(r["symbol"] for r in rows if r["market"] == market)
        shards.extend({"shard_id": f"{market}-{offset // size:03d}", "market": market,
                       "symbols": symbols[offset:offset + size]} for offset in range(0, len(symbols), size))
    plan = {"artifact": "RATE_FULL_MARKET_HISTORY_PLAN", "schema_version": "RATE-HISTORY-PLAN-V1",
            "as_of": catalogue["as_of"], "completed_through": completed,
            "catalogue": catalogue, "catalogue_sha256": digest(catalogue), "policy_id": catalogue["policy_id"],
            "policy_hash": policy_hash(), "contract": contract(), "owner_hashes": owners(),
            "runtime_authority": authority, "shards": shards, "fallback_used": False}
    plan["plan_id"] = "rate-history-plan-" + digest(plan)[:24]
    return plan


def validate_plan(plan):
    require(plan["artifact"] == "RATE_FULL_MARKET_HISTORY_PLAN" and plan["fallback_used"] is False,
            "HISTORY_PLAN_INVALID")
    validate_authority(plan["runtime_authority"])
    require(plan["plan_id"] == "rate-history-plan-" + digest({k: v for k, v in plan.items() if k != "plan_id"})[:24],
            "HISTORY_PLAN_HASH_MISMATCH")
    require(plan["policy_hash"] == policy_hash() and plan["contract"] == contract()
            and plan["owner_hashes"] == owners(), "HISTORY_OWNER_OR_POLICY_MISMATCH")
    validate_catalogue(plan["catalogue"], plan["as_of"])
    require(plan["catalogue_sha256"] == digest(plan["catalogue"]), "CATALOGUE_HASH_MISMATCH")
    from scripts.resolve_production_runtime_context import _previous_legal_trading_day
    require(plan["completed_through"] == _previous_legal_trading_day(plan["as_of"]), "COMPLETED_SESSION_BINDING_INVALID")
    expected = build_plan(plan["catalogue"], plan["runtime_authority"])
    require(plan == expected, "HISTORY_SHARD_PLAN_MISMATCH")
    return True


def safe_path(root, relative):
    root = Path(root).resolve()
    require(isinstance(relative, str) and not Path(relative).is_absolute() and "\\" not in relative,
            "HISTORY_PATH_INVALID")
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and ".." not in Path(relative).parts, "HISTORY_PATH_INVALID")
    return path


def put_bytes(root, relative, body):
    path = safe_path(root, relative)
    if path.exists():
        require(path.read_bytes() == body, "IMMUTABLE_HISTORY_CONFLICT")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    # A content-addressed object is never overwritten, including on retry.
    with path.open("xb") as stream:
        stream.write(body)
    return path


def put_json(root, relative, value):
    return put_bytes(root, relative, encoded(value))


def put_material(root, material):
    raw = encoded(material)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as stream:
        stream.write(raw)
    body = buffer.getvalue()
    sha = hashlib.sha256(body).hexdigest()
    require(len(body) < 90 * 1024 * 1024, "HISTORY_OBJECT_TOO_LARGE")
    path = "materials/" + sha + ".json.gz"
    put_bytes(root, path, body)
    return {"path": path, "sha256": sha, "content_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(body)}


def load_material(root, reference):
    body = safe_path(root, reference["path"]).read_bytes()
    require(len(body) == reference["bytes"] and hashlib.sha256(body).hexdigest() == reference["sha256"],
            "HISTORY_MATERIAL_HASH_MISMATCH")
    require(reference["path"] == "materials/" + reference["sha256"] + ".json.gz", "HISTORY_PATH_INVALID")
    raw = gzip.decompress(body)
    require(hashlib.sha256(raw).hexdigest() == reference["content_sha256"], "HISTORY_MATERIAL_HASH_MISMATCH")
    value = json.loads(raw)
    require(encoded(value) == raw, "HISTORY_CANONICAL_ENCODING_INVALID")
    return value


def official_receipt(receipt):
    endpoint = urlparse(receipt.get("endpoint", ""))
    host = endpoint.hostname or ""
    require(endpoint.scheme == "https" and any(host == domain or host.endswith("." + domain)
            for domain in ("twse.com.tw", "tpex.org.tw", "tdcc.com.tw")), "UNAUTHORIZED_HISTORY_PROVIDER")
    sha = receipt.get("content_hash", "")
    require(len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), "OFFICIAL_SOURCE_RECEIPT_MISSING")
    stamp = datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00"))
    require(stamp.tzinfo is not None and stamp <= datetime.now(timezone.utc), "SOURCE_FUTURE_DATED")
    require(receipt.get("parse_status") == "PASS", "OFFICIAL_SOURCE_RECEIPT_MISSING")


def unique_dated(rows, key, *, minimum, as_of, through):
    require(isinstance(rows, list) and len(rows) >= minimum, "HISTORICAL_WARMUP_REQUIRED")
    dates = [row[key] for row in rows]
    require(dates == sorted(dates) and len(dates) == len(set(dates)), "HISTORY_DUPLICATE_OR_UNORDERED_DATE")
    require(all(date.fromisoformat(day).isoformat() == day and day < as_of for day in dates), "FUTURE_DATED_HISTORY")
    from .cer080_multi_day_continuity import is_trading_day
    require(all(is_trading_day(day) for day in dates), "NON_TRADING_HISTORY_SESSION")
    require(dates[-1] == through, "STALE_HISTORY")
    return dates


def finite(row, keys, nonnegative=()):
    for key in keys:
        value = row[key]
        require(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value), "HISTORY_VALUE_INVALID")
        if key in nonnegative:
            require(value >= 0, "HISTORY_VALUE_INVALID")


def validate_symbol(material, plan, symbol, market):
    validate_authority(material["acquisition_runtime_authority"])
    require(material["artifact"] == "RATE_FULL_MARKET_SYMBOL_HISTORY"
            and material["plan_id"] == plan["plan_id"] and material["symbol"] == symbol
            and material["market"] == market and material["as_of"] == plan["as_of"]
            and material["fallback_used"] is False, "SYMBOL_HISTORY_BINDING_MISMATCH")
    require(set(material["source_receipts"]) == set(DOMAINS), "REQUIRED_HISTORY_DOMAIN_MISSING")
    for domain, receipts in material["source_receipts"].items():
        require(receipts, "OFFICIAL_SOURCE_RECEIPT_MISSING")
        for receipt in receipts:
            official_receipt(receipt)
            host = urlparse(receipt["endpoint"]).hostname
            expected_host = "tdcc.com.tw" if domain == "tdcc" else "twse.com.tw" if domain == "fundamental" or market == "TWSE" else "tpex.org.tw"
            require(host == expected_host or host.endswith("." + expected_host), "OFFICIAL_OWNER_MARKET_MISMATCH")
    cfg = contract()
    stocks, benchmark, institutional, tdcc, fundamental = (material[domain] for domain in DOMAINS)
    stock_dates = unique_dated(stocks, "trade_date", minimum=cfg["minimum_stock_sessions"], as_of=plan["as_of"], through=plan["completed_through"])
    bench_dates = unique_dated(benchmark, "trade_date", minimum=cfg["minimum_benchmark_sessions"], as_of=plan["as_of"], through=plan["completed_through"])
    require(stock_dates[-180:] == bench_dates[-180:], "HISTORICAL_WARMUP_REQUIRED:ALIGNED_SESSIONS")
    for row in stocks:
        require(row["symbol"] == symbol and row["market"] == market and row["source"] == market + "_STOCK_DAY", "STOCK_OFFICIAL_BINDING_INVALID")
        finite(row, ("open", "high", "low", "close", "volume", "turnover"), ("volume", "turnover"))
        require(row["close"] > 0 and row["low"] <= row["high"], "HISTORY_VALUE_INVALID")
    for row in benchmark:
        require(row["benchmark_symbol"] == ("TAIEX" if market == "TWSE" else "TPEX")
                and row["market"] == market and row["source"] == market + "_BENCHMARK_HISTORY", "BENCHMARK_MARKET_BINDING_INVALID")
        finite(row, ("close",))
        require(row["close"] > 0, "HISTORY_VALUE_INVALID")
    inst_dates = unique_dated(institutional, "trading_date", minimum=cfg["institutional_sessions"], as_of=plan["as_of"], through=plan["completed_through"])
    require(inst_dates[-26:] == stock_dates[-26:], "INSTITUTIONAL_SESSION_BINDING_INVALID")
    stock_by_date = {r["trade_date"]: r for r in stocks}
    from .institutional_history import T86_OFFICIAL_SOURCE, TPEX_OFFICIAL_SOURCE
    for row in institutional:
        require(row["symbol"] == symbol and row["official_source"] == (T86_OFFICIAL_SOURCE if market == "TWSE" else TPEX_OFFICIAL_SOURCE), "INSTITUTIONAL_OFFICIAL_BINDING_INVALID")
        finite(row, ("foreign_net_shares", "investment_trust_net_shares", "close", "turnover"))
        require(row["close"] == stock_by_date[row["trading_date"]]["close"]
                and row["turnover"] == stock_by_date[row["trading_date"]]["turnover"], "INSTITUTIONAL_STOCK_BINDING_INVALID")
    periods = [r["period_end"] for r in tdcc]
    require(periods == sorted(periods) and len(periods) == len(set(periods)), "TDCC_DUPLICATE_PERIOD")
    from .sources.tdcc_historical import select_required_period_union, holder_pct_400_from_tiers
    # Existing TDCC owner selects five actually available periods for every replay session.
    required_periods, _ = select_required_period_union(stock_dates[-7:], periods, 5)
    require(set(required_periods).issubset(periods), "HISTORICAL_WARMUP_REQUIRED:TDCC")
    for row in tdcc:
        require(row["period_end"] <= plan["completed_through"] and row["source"] == "TDCC Official Historical Query", "FUTURE_DATED_HISTORY")
        finite(row, ("holder_pct_400",))
        require(0 <= row["holder_pct_400"] <= 100 and row.get("raw_lineage"), "TDCC_OFFICIAL_BINDING_INVALID")
        require(row["holder_pct_400"] == holder_pct_400_from_tiers(row["raw_lineage"])
                and all(tier["symbol"] == symbol and tier["period_end"] == row["period_end"] for tier in row["raw_lineage"]),
                "TDCC_OFFICIAL_BINDING_INVALID")
    rev, eps = fundamental["revenue"], fundamental["eps"]
    require(len(rev) >= cfg["revenue_periods"] and len(eps) >= cfg["eps_quarters"], "HISTORICAL_WARMUP_REQUIRED:FUNDAMENTAL")
    require(len({r["revenue_period"] for r in rev}) == len(rev)
            and len({(r["fiscal_year"], r["quarter"]) for r in eps}) == len(eps), "FUNDAMENTAL_DUPLICATE_PERIOD")
    for row in rev + eps:
        require(row["symbol"] == symbol and row["provider"] == "MOPS Official"
                and row["official_disclosure_date"] <= plan["completed_through"], "FUNDAMENTAL_ASOF_BINDING_INVALID")
        require(row.get("endpoint") and len(row.get("content_hash", "")) == 64, "OFFICIAL_SOURCE_RECEIPT_MISSING")
    from .sources.fundamental_history import FundamentalHistoryStoreV2
    for row in rev:
        FundamentalHistoryStoreV2._validate_revenue_event(row)
        require(row["revenue_period"] <= plan["completed_through"][:7], "FUTURE_DATED_HISTORY")
        finite(row, ("revenue_yoy",))
    for row in eps:
        FundamentalHistoryStoreV2._validate_eps_event(row)
        require(row["quarter"] in (1, 2, 3, 4) and (row["fiscal_year"], row["quarter"]) <= (int(plan["completed_through"][:4]), (int(plan["completed_through"][5:7]) - 1) // 3), "FUTURE_DATED_HISTORY")
        finite(row, ("single_quarter_eps",))
    return {"stock_sessions": len(stocks), "benchmark_sessions": len(benchmark), "institutional_sessions": len(institutional),
            "tdcc_periods": len(tdcc), "revenue_periods": len(rev), "eps_quarters": len(eps), "validation_status": "PASS"}


def checkpoint_path(plan, symbol):
    return "progress/" + plan["plan_id"] + "/" + hashlib.sha256(symbol.encode()).hexdigest() + ".json"


def load_checkpoint(root, plan, symbol, market):
    path = safe_path(root, checkpoint_path(plan, symbol))
    if not path.exists():
        return None
    checkpoint = json.loads(path.read_bytes())
    require(checkpoint.get("artifact") == "RATE_HISTORY_SYMBOL_CHECKPOINT" and checkpoint.get("plan_id") == plan["plan_id"]
            and checkpoint.get("symbol") == symbol and checkpoint.get("market") == market, "CHECKPOINT_BINDING_INVALID")
    material = load_material(root, checkpoint["material"])
    require(checkpoint["coverage"] == validate_symbol(material, plan, symbol, market), "CHECKPOINT_COVERAGE_MISMATCH")
    return material, checkpoint


def persist_symbol(root, material, plan, symbol, market):
    coverage = validate_symbol(material, plan, symbol, market)
    reference = put_material(root, material)
    checkpoint = {"artifact": "RATE_HISTORY_SYMBOL_CHECKPOINT", "plan_id": plan["plan_id"],
                  "symbol": symbol, "market": market, "material": reference, "coverage": coverage}
    put_json(root, checkpoint_path(plan, symbol), checkpoint)
    return checkpoint


def snapshot_core(plan, checkpoints):
    count = len(checkpoints)
    return {"artifact": "RATE_FULL_MARKET_HISTORY_SNAPSHOT", "schema_version": "RATE-FULL-MARKET-HISTORY-SNAPSHOT-V1",
            "trading_date": plan["as_of"], "as_of": plan["as_of"], "completed_through": plan["completed_through"],
            "policy_id": plan["policy_id"], "policy_hash": plan["policy_hash"], "plan_id": plan["plan_id"],
            "eligible_count": count, "TWSE_eligible_count": contract()["expected_market_counts"]["TWSE"],
            "TPEX_eligible_count": contract()["expected_market_counts"]["TPEX"],
            **{name + "_coverage": f"{count}/{count}" for name in ("stock_history", "benchmark", "institutional", "tdcc", "fundamental", "stage_replay")},
            "minimum_stock_sessions": min(c["coverage"]["stock_sessions"] for c in checkpoints.values()),
            "material_hashes": {symbol: item["material"]["sha256"] for symbol, item in checkpoints.items()},
            "missing_symbols": [], "failed_symbols": [], "fallback_used": False, "validation_status": "PASS"}


def aggregate(root, plan):
    validate_plan(plan)
    by_symbol, checkpoints, missing = {}, {}, []
    for row in eligible(plan["catalogue"]):
        symbol, market = row["symbol"], row["market"]
        loaded = load_checkpoint(root, plan, symbol, market)
        if loaded is None:
            missing.append(symbol)
        else:
            by_symbol[symbol], checkpoints[symbol] = loaded
    if missing:
        return {"artifact": "RATE_FULL_MARKET_HISTORY_COVERAGE", "validation_status": "FAIL_CLOSED",
                "blocking_reason": "HISTORICAL_WARMUP_REQUIRED", "eligible_count": len(eligible(plan["catalogue"])),
                "complete_symbols": len(by_symbol), "missing_symbols": missing, "fallback_used": False}
    from .stage_history import build_stage_feature_histories
    stocks = {s: m["stock"] for s, m in by_symbol.items()}
    benchmarks = {s: m["benchmark"] for s, m in by_symbol.items()}
    institutional = {s: m["institutional"] for s, m in by_symbol.items()}
    tdcc = {s: m["tdcc"] for s, m in by_symbol.items()}
    # Replay uses the complete cross-section, never individual acquisition shards.
    replay = build_stage_feature_histories(stocks, benchmarks, institutional, tdcc,
                                         as_of_date=plan["completed_through"], sessions=7)
    require(set(replay) == set(by_symbol) and all(len(v) == 7 for v in replay.values()), "STAGE_REPLAY_COVERAGE_MISMATCH")
    stage_ref = put_material(root, {"artifact": "RATE_FULL_MARKET_STAGE_REPLAY", "plan_id": plan["plan_id"], "records": replay})
    shard_refs = []
    for shard in plan["shards"]:
        value = {"artifact": "RATE_FULL_MARKET_HISTORY_SHARD_MANIFEST", "plan_id": plan["plan_id"],
                 "shard": shard, "symbols": {s: checkpoints[s] for s in shard["symbols"]},
                 "validation_status": "PASS", "fallback_used": False}
        path = "shards/" + digest(value) + ".json"
        put_json(root, path, value)
        shard_refs.append({"path": path, "sha256": digest(value)})
    core = snapshot_core(plan, checkpoints)
    snapshot_id = "rate-full-market-history-" + digest(core)[:24]
    manifest = {"artifact": "RATE_FULL_MARKET_HISTORY_MANIFEST", "schema_version": "RATE-FULL-MARKET-HISTORY-MANIFEST-V1",
                "snapshot_id": snapshot_id, "snapshot_core_sha256": digest(core), "plan_sha256": digest(plan),
                "catalogue_sha256": digest(plan["catalogue"]), "owner_hashes": owners(), "shards": shard_refs,
                "materials": checkpoints, "stage_replay_material": stage_ref, "fallback_used": False,
                "validation_status": "PASS", "storage_authority": contract()["storage_authority"]}
    manifest_path = "manifests/" + digest(manifest) + ".json"
    put_json(root, manifest_path, manifest)
    snapshot = {**core, "snapshot_id": snapshot_id, "manifest": {"path": manifest_path, "sha256": digest(manifest)}}
    put_json(root, "snapshots/" + snapshot_id + ".json", snapshot)
    return snapshot


def reload_snapshot(root, plan, snapshot_id):
    validate_plan(plan)
    saved = json.loads(safe_path(root, "snapshots/" + snapshot_id + ".json").read_bytes())
    reference = saved["manifest"]
    manifest = json.loads(safe_path(root, reference["path"]).read_bytes())
    require(digest(manifest) == reference["sha256"] and reference["path"] == "manifests/" + digest(manifest) + ".json",
            "HISTORY_MANIFEST_HASH_MISMATCH")
    require(manifest["plan_sha256"] == digest(plan), "HISTORY_PLAN_HASH_MISMATCH")
    for shard in manifest["shards"]:
        require(hashlib.sha256(safe_path(root, shard["path"]).read_bytes()).hexdigest() == shard["sha256"], "HISTORY_SHARD_HASH_MISMATCH")
    require(manifest["owner_hashes"] == owners() and manifest["catalogue_sha256"] == digest(plan["catalogue"]), "HISTORY_OWNER_OR_POLICY_MISMATCH")
    checkpoints, materials = {}, {}
    for row in eligible(plan["catalogue"]):
        symbol = row["symbol"]
        loaded = load_checkpoint(root, plan, symbol, row["market"])
        require(loaded is not None, "HISTORICAL_WARMUP_REQUIRED")
        materials[symbol], checkpoints[symbol] = loaded
    require(manifest["materials"] == checkpoints, "HISTORY_MANIFEST_MATERIAL_BINDING_MISMATCH")
    require(len(manifest["shards"]) == len(plan["shards"]), "HISTORY_SHARD_COVERAGE_MISMATCH")
    for shard_reference, shard in zip(manifest["shards"], plan["shards"]):
        expected = {"artifact": "RATE_FULL_MARKET_HISTORY_SHARD_MANIFEST", "plan_id": plan["plan_id"],
                    "shard": shard, "symbols": {s: checkpoints[s] for s in shard["symbols"]},
                    "validation_status": "PASS", "fallback_used": False}
        require(shard_reference == {"path": "shards/" + digest(expected) + ".json", "sha256": digest(expected)}
                and json.loads(safe_path(root, shard_reference["path"]).read_bytes()) == expected,
                "HISTORY_SHARD_COVERAGE_MISMATCH")
    core = snapshot_core(plan, checkpoints)
    require(manifest["snapshot_core_sha256"] == digest(core) and manifest["snapshot_id"] == snapshot_id
            and snapshot_id == "rate-full-market-history-" + digest(core)[:24]
            and saved == {**core, "snapshot_id": snapshot_id, "manifest": reference}, "HISTORY_SNAPSHOT_BINDING_MISMATCH")
    from .stage_history import build_stage_feature_histories
    replay = build_stage_feature_histories({s: m["stock"] for s, m in materials.items()},
        {s: m["benchmark"] for s, m in materials.items()}, {s: m["institutional"] for s, m in materials.items()},
        {s: m["tdcc"] for s, m in materials.items()}, as_of_date=plan["completed_through"], sessions=7)
    stage = load_material(root, manifest["stage_replay_material"])
    require(stage == {"artifact": "RATE_FULL_MARKET_STAGE_REPLAY", "plan_id": plan["plan_id"], "records": replay},
            "STAGE_REPLAY_MATERIAL_BINDING_MISMATCH")
    return saved
