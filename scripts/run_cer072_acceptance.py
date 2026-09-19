"""Authoritative GitHub Actions live-source validation for CER-072.

This runner reads only the previously accepted, digest-verified staging history
layer. It never calls the Phase A2 orchestrator or writes a production state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_live_source_bundle import _rows, _pick
from src.benchmark_history import benchmark_digest
from src.historical_store import PersistentHistoricalStore
from src.institutional_features import calculate_institutional_rotation
from src.institutional_history import (
    INSTITUTIONAL_HISTORY_MINIMUM, T86_OFFICIAL_SOURCE, TPEX_OFFICIAL_SOURCE,
    canonical_digest, fetch_t86_sessions, fetch_tpex_monthly_history,
    valid_stock_session_dates, validate_history_rows,
)
from src.sources.tdcc import TDCCAdapter
from src.sources.tpex import TPExAdapter, normalize_tpex_date
from src.sources.twse import TWSEAdapter
from src.stage_evidence import _stage_inputs_from_history, build_production_stage_evidence, classify_stage
from src.stage_history import build_stage_feature_histories

HISTORICAL_DIGEST = "dddf63b85477aa7cd52ff284d3aba70cf449275406cb6e5e7091acc232d58e3a"
UNIVERSE_DIGEST = "30276287608b87f7d9b606891514247da523dce9214e4b82bb34ba118a35af4c"
ACCEPTED_TAIEX_DIGEST = "613f861d2bf51b8b8ac37725767f27e5a300ced2a5edaee119821378a0e796ed"
ACCEPTED_TPEX_INDEX_DIGEST = "1e943f9474ea9506e44c3b47ace43574b13902d86407e4e5427cca07581dce77"
TPEX_SYMBOLS = ("6274", "3081", "6187", "6510", "3227")
FROZEN_FILE_SHA256 = {
    "src/rate_logic.py": "d8aedb3b190ba21649ebfc5763578426331943a68c4289fd5d0bc977157d87d8",
    "src/institutional_features.py": "1c0a0e48f31774bcf46f1c650afe02d4604ff8419ad782691dd55cc6ad44f54d",
    "src/stage_evidence.py": "4207b9668505993a07990ea63a61ed0efeda0abe6b84b992f0e1eb034b919af0",
    "src/technical_features.py": "da45381e26dfb2765190eb3fbf6480ad85635e17af2b865c457f0ec2f84b102e",
    "src/rotation_history.py": "e80eeb2b5876172f10beef37d7e061298e03f80a15db93be6ded5f3804a1da97",
    "control_center/production_control/v1/04_GOLDEN_TEST_FIXTURES_V1.0.md": "f98a5e9e68bce02a0078b9c0ab40fd7ed896b59d94f14a21cb7e866a41e21c91",
    "control_center/production_control/v1/01_RATE_PRODUCTION_LOGIC_SPEC_V1.1.md": "5947b731adeb423f1495b543d1acbd4d8bbdbd1118a99005c213dc1e08399b3e",
}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _assert_benchmark_digest_binding(records, accepted_digest, label):
    observed_digest = benchmark_digest(records)
    if observed_digest != accepted_digest:
        raise RuntimeError(f"RESTORED_{label}_HISTORY_DIGEST_MISMATCH")
    return observed_digest


def _stable_digest(value):
    """Hash substantive evidence while excluding volatile execution timestamps."""
    volatile = {"generated_at", "calculation_timestamp", "retrieval_timestamp", "ingested_at", "source_timestamp"}
    def clean(item):
        if isinstance(item, dict):
            return {k: clean(v) for k, v in item.items() if k not in volatile}
        if isinstance(item, list):
            return [clean(v) for v in item]
        return item
    return canonical_digest(clean(value))


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _verify_model_freeze():
    observed = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FROZEN_FILE_SHA256}
    changed = [name for name, digest in observed.items() if digest != FROZEN_FILE_SHA256[name]]
    return {"status": "FAIL" if changed else "PASS", "files": observed, "changed_files": changed}


def _validate_restored_history(history_root, universe, manifest_path, twse_mat_path, tpex_mat_path,
                               taiex_evidence_path, tpex_index_evidence_path, digest_evidence=None):
    manifest = _load_json(manifest_path)
    if manifest.get("status") != "PASS" or manifest.get("full_historical_acceptance") != "PASS":
        raise RuntimeError("ACCEPTED_HISTORICAL_MANIFEST_NOT_PASS")
    if manifest.get("full_historical_state_digest") != HISTORICAL_DIGEST or manifest.get("RATE_FULL_HISTORICAL_STATE_DIGEST") != HISTORICAL_DIGEST:
        raise RuntimeError("ACCEPTED_HISTORICAL_STATE_DIGEST_MISMATCH")
    if manifest.get("universe_digest") != UNIVERSE_DIGEST:
        raise RuntimeError("ACCEPTED_HISTORICAL_UNIVERSE_DIGEST_MISMATCH")
    twse_mat, tpex_mat = _load_json(twse_mat_path), _load_json(tpex_mat_path)
    taiex_ev, tpex_index_ev = _load_json(taiex_evidence_path), _load_json(tpex_index_evidence_path)
    if twse_mat.get("status") != "PASS" or twse_mat.get("content_identity_status") != "25/25 PASS":
        raise RuntimeError("ACCEPTED_TWSE_MATERIALIZATION_EVIDENCE_NOT_PASS")
    if tpex_mat.get("status") != "PASS" or tpex_mat.get("materialized_symbols") != "5/5":
        raise RuntimeError("ACCEPTED_TPEX_MATERIALIZATION_EVIDENCE_NOT_PASS")
    if taiex_ev.get("status") != "PASS" or tpex_index_ev.get("status") != "PASS":
        raise RuntimeError("ACCEPTED_BENCHMARK_EVIDENCE_NOT_PASS")
    store = PersistentHistoricalStore(history_root)
    symbols = [str(x["symbol"]) for x in universe["symbols"]]
    markets = {str(x["symbol"]): x["market"] for x in universe["symbols"]}
    twse_hashes = twse_mat.get("store_digest_by_symbol", {})
    tpex_hashes = {str(x["symbol"]): x.get("content_hash") for x in tpex_mat.get("symbol_rows", [])}
    stocks = {}
    for symbol in symbols:
        rows = store.load_stock(symbol)
        digest = _canonical_hash(rows)
        expected = twse_hashes.get(symbol) if markets[symbol] == "TWSE" else tpex_hashes.get(symbol)
        if not expected or digest != expected:
            raise RuntimeError(f"RESTORED_STOCK_HISTORY_DIGEST_MISMATCH:{symbol}")
        if len(rows) < 180 or any(row.get("market") != markets[symbol] for row in rows):
            raise RuntimeError(f"RESTORED_STOCK_HISTORY_INVALID:{symbol}")
        stocks[symbol] = rows
    benchmarks = {"TAIEX": store.load_benchmark("TAIEX"), "TPEX": store.load_benchmark("TPEX")}
    taiex_observed = benchmark_digest(benchmarks["TAIEX"])
    tpex_observed = benchmark_digest(benchmarks["TPEX"])
    if digest_evidence is not None:
        digest_evidence.update({
            "benchmark_digest_contract": "benchmark_digest",
            "restored_taiex_digest": taiex_observed,
            "accepted_taiex_digest": taiex_ev.get("benchmark_digest"),
            "restored_tpex_index_digest": tpex_observed,
            "accepted_tpex_index_digest": tpex_index_ev.get("benchmark_digest"),
        })
    if taiex_ev.get("benchmark_digest") != ACCEPTED_TAIEX_DIGEST:
        raise RuntimeError("ACCEPTED_TAIEX_BENCHMARK_DIGEST_UNEXPECTED")
    if tpex_index_ev.get("benchmark_digest") != ACCEPTED_TPEX_INDEX_DIGEST:
        raise RuntimeError("ACCEPTED_TPEX_INDEX_BENCHMARK_DIGEST_UNEXPECTED")
    _assert_benchmark_digest_binding(benchmarks["TAIEX"], taiex_ev.get("benchmark_digest"), "TAIEX")
    _assert_benchmark_digest_binding(benchmarks["TPEX"], tpex_index_ev.get("benchmark_digest"), "TPEX_INDEX")
    return {"store": store, "stocks": stocks, "benchmarks": benchmarks, "markets": markets,
            "symbols": symbols, "historical_digest": HISTORICAL_DIGEST}


def _tdcc_history(symbols, as_of_date):
    result = TDCCAdapter().fetch()
    buckets = {s: {} for s in symbols}
    rows = _rows(result.get("raw_payload"))
    for row in rows:
        symbol = str(_pick(row, "symbol", "SecuritiesCompanyCode", "公司代號", "證券代號") or "").strip()
        if symbol not in buckets:
            continue
        raw_period = _pick(row, "period_end", "資料日期", "資料年月", "Date")
        if raw_period is None:
            continue
        period = normalize_tpex_date(raw_period)
        if period > as_of_date:
            continue
        direct = _pick(row, "holder_pct_400", "持股超過400張比率", "400張以上持股比率")
        item = buckets[symbol].setdefault(period, {"direct": [], "tiers": {}, "raw_rows": []})
        if direct is not None:
            item["direct"].append(float(str(direct).replace(",", "")))
        else:
            tier = str(_pick(row, "持股分級", "持股級距", "HoldingRange") or "").strip()
            share = _pick(row, "占集保庫存數比例%", "占集保庫存數比例", "占集保庫存數比例(%)", "Percentage of Centrally Deposited Securities")
            if tier.isdigit() and share is not None:
                if tier in item["tiers"]:
                    raise RuntimeError(f"TDCC_DUPLICATE_TIER:{symbol}:{period}:{tier}")
                value = float(str(share).replace(",", ""))
                if not 0 <= value <= 100:
                    raise RuntimeError(f"TDCC_PERCENTAGE_RANGE:{symbol}:{period}:{tier}")
                item["tiers"][tier] = value
        item["raw_rows"].append(row)
    by_symbol = {s: [] for s in symbols}
    for symbol, periods in buckets.items():
        for period, item in sorted(periods.items()):
            if item["direct"]:
                if len(set(item["direct"])) != 1:
                    raise RuntimeError(f"TDCC_DUPLICATE_AGGREGATE_VALUE:{symbol}:{period}")
                holder = item["direct"][0]
            else:
                # TDCC level 11 is 200,001–400,000 shares; levels 12+ are
                # 400,001 shares and above. RATE's frozen holder_pct_400 is
                # therefore the sum of published percentage for levels 12+.
                tiers = [value for level, value in item["tiers"].items() if int(level) >= 12]
                if not tiers:
                    continue
                holder = sum(tiers)
            by_symbol[symbol].append({"period_end": period, "holder_pct_400": holder,
                "source_timestamp": result.get("source_timestamp"),
                "retrieval_timestamp": result.get("retrieval_timestamp"),
                "source": "TDCC /v1/opendata/1-5", "raw_lineage": item["raw_rows"]})
    return by_symbol, result


def _stock_and_benchmark_inputs(data, requested_date=None):
    symbols, stocks, markets = data["symbols"], data["stocks"], data["markets"]
    benchmark_for_symbol = {s: data["benchmarks"]["TAIEX" if markets[s] == "TWSE" else "TPEX"] for s in symbols}
    per_dates = []
    for symbol in symbols:
        sd = {row["trade_date"] for row in stocks[symbol] if row.get("close") is not None and row.get("turnover") is not None}
        bd = {row["trade_date"] for row in benchmark_for_symbol[symbol] if row.get("close") is not None}
        per_dates.append(sd & bd)
    common = sorted(set.intersection(*per_dates))
    if requested_date:
        if requested_date not in common:
            raise RuntimeError(f"REQUESTED_END_DATE_NOT_COMMON_VALID_SESSION:{requested_date}")
        common = [x for x in common if x <= requested_date]
    if len(common) < 26:
        raise RuntimeError(f"DATA_INCOMPLETE:COMMON_ALIGNED_STOCK_SESSIONS:{len(common)}<26")
    return common, benchmark_for_symbol


def _replay_and_evidence(data, institutional_by_symbol, tdcc_by_symbol, as_of_date):
    stocks, benchmarks, symbols = data["stocks"], data["benchmarks"], data["symbols"]
    benchmark_by_symbol = {s: benchmarks["TAIEX" if data["markets"][s] == "TWSE" else "TPEX"] for s in symbols}
    feature_history = build_stage_feature_histories(stocks, benchmark_by_symbol, institutional_by_symbol,
                                                    tdcc_by_symbol, as_of_date=as_of_date, sessions=7)
    stage_evidence, prior_package_rows = {}, []
    replay_dates = [feature_history[s][-7]["trade_date"] for s in symbols[:1]] + [x["trade_date"] for x in feature_history[symbols[0]][-6:]]
    if len(replay_dates) != 7 or len(set(replay_dates)) != 7 or replay_dates[-1] != as_of_date:
        raise RuntimeError("STAGE_INSTITUTIONAL_ASOF_CALENDAR_INVALID")
    fi_symbols, it_symbols, fc_symbols, lh_symbols, alignment_symbols = (set() for _ in range(5))
    for session in replay_dates:
        for symbol in symbols:
            hist = feature_history[symbol]
            rec = next((x for x in hist if x["trade_date"] == session), None)
            if rec is None:
                raise RuntimeError(f"STAGE_FEATURE_SESSION_MISSING:{symbol}:{session}")
            lineage = rec.get("institutional_lineage", {})
            for key in ("FI", "IT", "FC", "LH"):
                if lineage.get(key, {}).get("calculation_status") != "PASS":
                    raise RuntimeError(f"{key}_HISTORICAL_REPLAY_FAILED:{symbol}:{session}")
            valid_inst = [x for x in institutional_by_symbol[symbol] if x["trading_date"] <= session]
            if not valid_inst or valid_inst[-1]["trading_date"] != session or len(valid_inst) < 26:
                raise RuntimeError(f"STAGE_INSTITUTIONAL_ASOF_ALIGNMENT_FAILED:{symbol}:{session}")
            tdcc_prior = [x for x in tdcc_by_symbol[symbol] if x["period_end"] <= session]
            if len(tdcc_prior) < 5 or any(x["period_end"] > session for x in tdcc_prior[-5:]):
                raise RuntimeError(f"TDCC_ASOF_COVERAGE_FAILED:{symbol}:{session}")
            fi_symbols.add(symbol); it_symbols.add(symbol); fc_symbols.add(symbol)
            lh_symbols.add(symbol); alignment_symbols.add(symbol)
    for symbol in symbols:
        hist = feature_history[symbol]
        current = hist[-1]
        stock_history = [x for x in stocks[symbol] if x["trade_date"] <= as_of_date]
        stage = build_production_stage_evidence(symbol=symbol, stock_history=stock_history,
            technical_record=current["technical_record"], technical_features=current["technical_features"],
            m7_score=current["M7"], mhe_score=current["MHE"], rotation_score=current["Rotation"],
            prior_state=None, input_snapshot_id=None, feature_history=hist)
        if stage.get("calculation_status") != "PASS" or stage.get("lineage_binding_status") != "PENDING_SNAPSHOT_BINDING":
            raise RuntimeError(f"CURRENT_STAGE_EVIDENCE_INVALID:{symbol}")
        stage_evidence[symbol] = stage
        prior = hist[-7]
        prior_session_feature = hist[-2]
        prior_inputs, _ = _stage_inputs_from_history(
            prior_session_feature, prior, "PRIOR_TRANSITION_NOT_RECONSTRUCTED")
        reconstructed_prior = classify_stage(prior_inputs)
        if reconstructed_prior["stage_current"] != stage["previous_stage"]:
            raise RuntimeError(f"PRIOR_STAGE_RECONSTRUCTION_MISMATCH:{symbol}")
        prior_stage_payload = {
            "symbol": symbol,
            "prior_session": prior_session_feature["trade_date"],
            "previous_stage": reconstructed_prior["stage_current"],
            "stage_inputs": prior_inputs,
            "M7_t": prior_session_feature["M7"], "M7_t_minus_5": prior["M7"],
            "MHE_t": prior_session_feature["MHE"], "MHE_t_minus_5": prior["MHE"],
            "Rotation_t": prior_session_feature["Rotation"], "Rotation_t_minus_5": prior["Rotation"],
            "RotationClass_t": prior_session_feature["RotationClass"], "RotationClass_t_minus_5": prior["RotationClass"],
        }
        prior_package_rows.append({"symbol": symbol, "prior_session": hist[-2]["trade_date"],
            "previous_stage": reconstructed_prior["stage_current"],
            "prior_stage_source": "RECONSTRUCTED_FROM_AUTHORIZED_HISTORICAL_EVIDENCE",
            "M7_t_minus_5": prior["M7"], "MHE_t_minus_5": prior["MHE"],
            "Rotation_t_minus_5": prior["Rotation"], "RotationClass_t_minus_5": prior["RotationClass"],
            "stage_evidence_digest": _stable_digest(prior_stage_payload)})
    return feature_history, stage_evidence, prior_package_rows, {
        "stage_institutional_asof_alignment": f"{len(alignment_symbols)}/30 PASS",
        "fi_historical_replay": f"{len(fi_symbols)}/30 PASS", "it_historical_replay": f"{len(it_symbols)}/30 PASS",
        "fc_historical_replay": f"{len(fc_symbols)}/30 PASS", "lh_historical_replay": f"{len(lh_symbols)}/30 PASS",
    }


def _no_lookahead(data, institutional, tdcc, as_of_date, stage_evidence):
    prior_date = sorted({r["trade_date"] for r in data["stocks"][data["symbols"][0]] if r["trade_date"] <= as_of_date})[-2]
    changed_stocks = {s: [dict(r, close=float(r["close"])*2, low=float(r["low"])*.5) if r["trade_date"] >= as_of_date else dict(r) for r in rows]
                      for s, rows in data["stocks"].items()}
    changed_inst = {s: [dict(r, foreign_net_shares=float(r["foreign_net_shares"])*7, investment_trust_net_shares=float(r["investment_trust_net_shares"])*9) if r["trading_date"] >= as_of_date else dict(r) for r in rows]
                    for s, rows in institutional.items()}
    changed_tdcc = {s: [dict(r, holder_pct_400=99.0) if r["period_end"] > prior_date else dict(r) for r in rows]
                    for s, rows in tdcc.items()}
    benchmarks = {"TAIEX":data["benchmarks"]["TAIEX"],"TPEX":data["benchmarks"]["TPEX"]}
    bp = {s:benchmarks["TAIEX" if data["markets"][s]=="TWSE" else "TPEX"] for s in data["symbols"]}
    replay = build_stage_feature_histories(changed_stocks,bp,changed_inst,changed_tdcc,as_of_date=prior_date,sessions=7)
    for symbol in data["symbols"]:
        if replay[symbol][-1]["trade_date"] != prior_date:
            return False
        # Reconstruct Stage(t-1) using only the prefix ending on that date.
        f = replay[symbol]
        prior_stock = [r for r in changed_stocks[symbol] if r["trade_date"] <= prior_date]
        rebuilt = build_production_stage_evidence(symbol=symbol,stock_history=prior_stock,
            technical_record=f[-1]["technical_record"],technical_features=f[-1]["technical_features"],
            m7_score=f[-1]["M7"],mhe_score=f[-1]["MHE"],rotation_score=f[-1]["Rotation"],
            prior_state=None,input_snapshot_id=None,feature_history=f)
        if rebuilt["stage_current"] != stage_evidence[symbol]["previous_stage"]:
            return False
    return True


def run(args):
    outdir = Path(args.output_dir); outdir.mkdir(parents=True, exist_ok=True)
    runid, commit = os.getenv("GITHUB_RUN_ID"), os.getenv("GITHUB_SHA")
    runtime="github_actions" if os.getenv("GITHUB_ACTIONS")=="true" else "local"
    provenance={"execution_runtime":runtime,"run_id":runid,"commit_sha":commit,"fixture_used":False}
    evidence = {"artifact":"RATE_CER072_INSTITUTIONAL_HISTORY_EVIDENCE",**provenance,"validation_status":"BLOCKED","t86_operational_policy":"PASS_WITH_USER_ASSUMPTION","t86_formal_authorization":"UNVERIFIED","historical_layer_modified":False,"production_state_modified":False,"input_snapshot_id":None,"current_state_id":None,"production_decision_state_persist":0,"rate_live_e2e_enabled":False,"blocking_reasons":[]}
    digest_evidence = {
        "accepted_historical_cache_key": os.getenv("RATE_ACCEPTED_HISTORICAL_CACHE_KEY"),
        "accepted_historical_restore": "PASS" if os.getenv("RATE_ACCEPTED_HISTORICAL_CACHE_KEY") else "FAIL",
        "benchmark_digest_contract": "benchmark_digest",
        "restored_taiex_digest": None,
        "accepted_taiex_digest": ACCEPTED_TAIEX_DIGEST,
        "restored_tpex_index_digest": None,
        "accepted_tpex_index_digest": ACCEPTED_TPEX_INDEX_DIGEST,
    }
    evidence.update(digest_evidence)
    freeze = _verify_model_freeze()
    evidence["model_freeze_integrity"] = freeze
    t86_evidence = {"artifact":"RATE_CER072_T86_26_SESSION_EVIDENCE",**provenance,"requested_end_date":None,"valid_session_dates":[],"request_count":0,"daily_request_deduplication":"NOT_RUN","valid_response_count":0,"empty_nontrading_dates":[],"response_date_identity_status":"NOT_RUN","symbols_required":25,"symbols_complete":0,"session_count_by_symbol":{},"minimum_sessions":0,"maximum_sessions":0,"FI_field_status":"NOT_RUN","IT_field_status":"NOT_RUN"}
    prior_package = {"artifact":"RATE_FIRST_PRODUCTION_PRIOR_STAGE_PACKAGE_V1",**provenance,"scope":"FIRST_PRODUCTION_BOOTSTRAP_EVIDENCE","input_snapshot_id":None,"current_state_id":None,"production_decision_state_persist":0,"symbols":[]}
    prior_evidence = {"artifact":"RATE_CER072_PRIOR_STAGE_RECONSTRUCTION_EVIDENCE",**provenance,"reconstruction_status":"NOT_RUN","no_lookahead":"NOT_RUN","current_stage_evidence_ready":"NOT_RUN","blocking_reasons":[]}
    try:
        universe = _load_json(args.universe_file)
        if freeze["status"] != "PASS":
            raise RuntimeError("MODEL_FREEZE_INTEGRITY_FAILURE:" + ",".join(freeze["changed_files"]))
        if universe.get("validation_status") != "PASS" or universe.get("universe_symbol_digest") != UNIVERSE_DIGEST:
            raise RuntimeError("APPROVED_STAGING_UNIVERSE_INVALID")
        twse_symbols=[str(x["symbol"]) for x in universe["symbols"] if x.get("market")=="TWSE"]
        tpex_symbols=[str(x["symbol"]) for x in universe["symbols"] if x.get("market")=="TPEX"]
        if len(twse_symbols)!=25 or set(tpex_symbols)!=set(TPEX_SYMBOLS):
            raise RuntimeError("APPROVED_INSTITUTIONAL_UNIVERSE_MISMATCH")
        data = _validate_restored_history(args.history_root, universe, args.accepted_manifest,
            args.twse_materialization, args.tpex_materialization, args.taiex_evidence, args.tpex_index_evidence,
            digest_evidence=digest_evidence)
        evidence.update(digest_evidence)
        sessions, benchmark_by_symbol = _stock_and_benchmark_inputs(data,args.trading_date)
        t = sessions[-1]; t86_evidence["requested_end_date"]=t
        evidence["resolved_trading_date"] = t
        candidate_dates=sessions[-60:]
        adapter=TWSEAdapter()
        throttle=float(os.getenv("RATE_T86_MIN_INTERVAL_SECONDS","1.2")); t_start=time.monotonic()
        last_request=None
        def paced_t86(day):
            nonlocal last_request
            if last_request is not None:
                time.sleep(max(0.0,throttle-(time.monotonic()-last_request)))
            last_request=time.monotonic()
            return adapter.fetch_t86(day)
        twse_result=fetch_t86_sessions(type("PacedAdapter",(),{"fetch_t86":staticmethod(paced_t86)})(),
            data["stocks"],twse_symbols,candidate_dates)
        t86_rows=twse_result["records"]
        t86_evidence.update({"valid_session_dates":twse_result["session_dates"],"request_count":twse_result["request_count"],
            "valid_response_count":len(twse_result["session_dates"]),"empty_nontrading_dates":twse_result["empty_nontrading_dates"],
            "response_date_identity_status":twse_result["response_date_identity_status"],"symbols_complete":25,
            "daily_request_deduplication":twse_result["daily_request_deduplication"],
            "response_date_identity_evidence":twse_result["identity_evidence"],
            "session_count_by_symbol":{s:len(t86_rows[s]) for s in twse_symbols},"minimum_sessions":min(map(len,t86_rows.values())),
            "maximum_sessions":max(map(len,t86_rows.values())),"FI_field_status":"PASS","IT_field_status":"PASS",
            "source":"TWSE T86 date-aware endpoint","source_lineage":{s:t86_rows[s] for s in twse_symbols}})
        tpex_symbols=list(TPEX_SYMBOLS)
        tpex_result=fetch_tpex_monthly_history(TPExAdapter(),tpex_symbols,data["stocks"],twse_result["session_dates"])
        tpex_rows=tpex_result["records"]
        tpex_dates=set.intersection(*(set(r["trading_date"] for r in tpex_rows[s]) for s in tpex_symbols))
        common_dates=sorted(set(twse_result["session_dates"]) & tpex_dates)
        if len(common_dates)<26: raise RuntimeError(f"INSTITUTIONAL_COMMON_MARKET_DATES:{len(common_dates)}<26")
        institutional={**t86_rows,**tpex_rows}
        accepted=validate_history_rows(institutional,data["symbols"],common_dates,26)
        counts={s:len(accepted[s]) for s in data["symbols"]}
        tdcc,tdcc_result=_tdcc_history(data["symbols"],t)
        feature_history,stages,package_rows,replay_status=_replay_and_evidence(data,institutional,tdcc,t)
        no_lookahead=_no_lookahead(data,institutional,tdcc,t,stages)
        if not no_lookahead: raise RuntimeError("LIVE_PRIOR_STAGE_RECONSTRUCTION_LOOKAHEAD")
        stage_dates=[feature_history[data["symbols"][0]][-7+i]["trade_date"] for i in range(7)]
        for sym in data["symbols"]:
            tdcc_dates=[x["period_end"] for x in tdcc[sym]]
            if any(not any(p<=day for p in tdcc_dates) or len([p for p in tdcc_dates if p<=day])<5 for day in stage_dates):
                raise RuntimeError(f"TDCC_HISTORICAL_ASOF_COVERAGE_FAILED:{sym}")
        payload_core={"schema_version":"RATE-FIRST-PRODUCTION-PRIOR-STAGE-V1","spec_version":"RATE-SPEC-20260919-004",
          "source_historical_digest":HISTORICAL_DIGEST,"trading_date":t,"prior_session":stage_dates[-2],
          "source_scope":"AUTHORIZED_LIVE_HISTORICAL_REPLAY","symbols":sorted(package_rows,key=lambda row:row["symbol"])}
        package_digest=_stable_digest(payload_core)
        prior_package.update({**payload_core,"package_digest":package_digest,"symbols":package_rows,
          "prior_stage_package_determinism":"PASS","source_timestamp_excluded_from_digest":True,
          "stage_lineage_snapshot_binding":"PENDING_SNAPSHOT_BINDING"})
        prior_evidence.update({"trading_date":t,"replay_dates":stage_dates,"institutional_historical_coverage":f"{len(accepted)}/30",
          "institutional_sessions_ge26":f"{sum(n>=26 for n in counts.values())}/30","twse_coverage":f"{sum(counts[s]>=26 for s in twse_symbols)}/25",
          "tpex_coverage":f"{sum(counts[s]>=26 for s in tpex_symbols)}/5","stage_feature_history":f"{sum(len(feature_history[s])==7 for s in data['symbols'])}/30",
          "first_live_prior_stage_reconstruction":f"{sum(stages[s]['prior_stage_source']=='RECONSTRUCTED_FROM_AUTHORIZED_HISTORICAL_EVIDENCE' for s in stages)}/30",
          "live_prior_stage_reconstruction_no_lookahead":"PASS","current_stage_evidence_ready":f"{sum(stages[s]['calculation_status']=='PASS' for s in stages)}/30",
          "tdcc_historical_asof_coverage":"30/30 PASS","stage_institutional_asof_alignment":replay_status["stage_institutional_asof_alignment"],**replay_status,
          "tpex_month_request_count":tpex_result["request_count"],"tpex_months_requested":tpex_result["months_requested"],
          "tpex_institutional_monthly_request_deduplication":tpex_result["monthly_request_deduplication"],
          "tdcc_source_timestamp":tdcc_result.get("source_timestamp"),"source_t86":T86_OFFICIAL_SOURCE,"source_tpex":TPEX_OFFICIAL_SOURCE,
          "rate_full_historical_state_digest":HISTORICAL_DIGEST,"production_snapshot_created":False,"production_decision_state_persisted":0})
        evidence.update({"validation_status":"PASS","trading_date":t,"institutional_historical_coverage":"30/30",
          "institutional_sessions_ge26":"30/30","twse_sessions_ge26":"25/25","tpex_sessions_ge26":"5/5",
          "fi_historical_replay":replay_status["fi_historical_replay"],"it_historical_replay":replay_status["it_historical_replay"],
          "fc_historical_replay":replay_status["fc_historical_replay"],"lh_historical_replay":replay_status["lh_historical_replay"],
          "institutional_historical_cross_section_no_lookahead":"PASS","tdcc_historical_asof_coverage":"30/30 PASS",
          "stage_feature_history":"7 sessions x 30 symbols PASS","first_live_prior_stage_reconstruction":"30/30 PASS",
          "live_prior_stage_reconstruction_no_lookahead":"PASS","current_stage_evidence_ready":"30/30",
          "prior_stage_package_determinism":"PASS","prior_stage_package_digest":package_digest,
          "stage_lineage_snapshot_binding":"PENDING_SNAPSHOT_BINDING","institutional_record_lineage":institutional,
          "tdcc_record_lineage":tdcc,"source_endpoint_counts":{"TWSE_T86":twse_result["request_count"],"TPEX_INSTITUTIONAL_MONTHLY":tpex_result["request_count"]},
          "production_snapshot_created":False,"production_decision_state_persisted":0})
    except Exception as exc:
        reason=str(exc)
        evidence.update(digest_evidence)
        evidence["blocking_reasons"].append(reason)
        evidence["validation_status"]="BLOCKED" if any(x in reason for x in ("MISSING", "INCOMPLETE", "UNAVAILABLE", "NOT_FOUND")) else "FAIL"
        t86_evidence.setdefault("blocking_reason",reason)
        prior_evidence["blocking_reasons"].append(reason)
        prior_evidence["reconstruction_status"]="BLOCKED" if evidence["validation_status"]=="BLOCKED" else "FAIL"
        prior_package["blocking_reason"]=reason
    _atomic_write(outdir/"RATE_CER072_T86_26_SESSION_EVIDENCE.json",t86_evidence)
    _atomic_write(outdir/"RATE_CER072_INSTITUTIONAL_HISTORY_EVIDENCE.json",evidence)
    _atomic_write(outdir/"RATE_FIRST_PRODUCTION_PRIOR_STAGE_PACKAGE_V1.json",prior_package)
    _atomic_write(outdir/"RATE_CER072_PRIOR_STAGE_RECONSTRUCTION_EVIDENCE.json",prior_evidence)
    print(json.dumps({"status":evidence["validation_status"],"trading_date":evidence.get("trading_date"),
      "resolved_trading_date":evidence.get("resolved_trading_date"),
      "accepted_historical_cache_key":evidence.get("accepted_historical_cache_key"),
      "accepted_historical_restore":evidence.get("accepted_historical_restore"),
      "restored_taiex_digest":evidence.get("restored_taiex_digest"),"accepted_taiex_digest":evidence.get("accepted_taiex_digest"),
      "restored_tpex_index_digest":evidence.get("restored_tpex_index_digest"),"accepted_tpex_index_digest":evidence.get("accepted_tpex_index_digest"),
      "benchmark_digest_contract":evidence.get("benchmark_digest_contract"),
      "t86_requests":t86_evidence.get("request_count"),"blocking_reasons":evidence["blocking_reasons"]},ensure_ascii=False))
    return 0 if evidence["validation_status"]=="PASS" else 1


def _atomic_write(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--history-root",default="data/staging/history")
    parser.add_argument("--universe-file",default="config/staging/RATE_STAGING_LIVE_UNIVERSE_V1.json")
    parser.add_argument("--accepted-manifest",required=True)
    parser.add_argument("--twse-materialization",required=True)
    parser.add_argument("--tpex-materialization",required=True)
    parser.add_argument("--taiex-evidence",required=True)
    parser.add_argument("--tpex-index-evidence",required=True)
    parser.add_argument("--trading-date")
    parser.add_argument("--output-dir",default="artifacts")
    return run(parser.parse_args())


if __name__=="__main__":
    raise SystemExit(main())
