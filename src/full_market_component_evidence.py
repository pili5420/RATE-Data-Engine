"""Opt-in, offline full-universe evidence assembly using unchanged owners."""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timezone
import math
from pathlib import Path
from urllib.parse import urlparse

from .eps_duration_facts.model import require
from .fundamental_first_refresh_execution import canonical, digest, exact_universe
from .provider_eps_metadata import read_metadata
from .provider_eps_candidate import _time
from .full_market_history import put_bytes
from .technical_features import compute_scores, technical_record
from .rotation_history import build_rotation_feature_histories
from .institutional_features import calculate_institutional_rotation
from .rate_logic import calculate_m7, calculate_mhe, calculate_smart_money
from .stage_evidence import build_production_stage_evidence, STAGE_OPERATIONAL_SPEC_VERSION
from .sources.tdcc_historical import select_required_period_union
from .fundamental_ranking_consumer import RANK_INPUTS, CONTRACT as FUNDAMENTAL_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = read_metadata((ROOT / "docs/contracts/RATE_FULL_MARKET_COMPONENT_EVIDENCE_V1.json").read_bytes())
KIND = CONTRACT["artifact_kind"]
COMPONENTS = tuple(CONTRACT["components"])
OWNERS = {"M7": "src/rate_logic.py::calculate_m7", "MHE": "src/rate_logic.py::calculate_mhe",
          "Stage": "src/stage_evidence.py::build_production_stage_evidence",
          "Rotation": "src/institutional_features.py::calculate_institutional_rotation",
          "SmartMoney": "src/institutional_features.py::calculate_institutional_rotation",
          "RelativeStrength": "src/technical_features.py::compute_scores",
          "Liquidity": "src/technical_features.py::compute_scores"}
SYNTHETIC = "SYNTHETIC_ENGINEERING_ONLY_NOT_PRODUCTION_ACCEPTANCE"
REAL = CONTRACT["source_scope"]
FAMILIES = ("stock", "benchmark", "institutional", "tdcc")


def now():
    return datetime.now(timezone.utc).isoformat()


def owners():
    result = {}
    for path, expected in CONTRACT["owner_code_sha256_lf"].items():
        body = (ROOT / path).read_bytes()
        require(digest(body.replace(b"\r\n", b"\n")) == expected, "COMPONENT_OWNER_SHA_DRIFT:" + path)
        result[path] = expected
    return result


def pinned(ref):
    require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "COMPONENT_REFERENCE_SCHEMA")
    body = Path(ref["path"]).read_bytes()
    require(digest(body) == ref["sha256"], "COMPONENT_SOURCE_HASH_MISMATCH")
    return body


def load_sources(binding, *, trusted_acceptance_sha256, as_of, synthetic=False):
    """Replay an independently accepted normalization, not a caller's raw values.

    Acceptance is a separate trust anchor supplied by the controlled source owner.
    It pins the normalized history, parser identities, and exact raw/receipt set.
    This reader never manufactures such acceptance from an unvalidated payload.
    """
    require(binding["acceptance"]["sha256"] == trusted_acceptance_sha256,
            "COMPONENT_TRUSTED_SOURCE_ACCEPTANCE_REQUIRED")
    acceptance = read_metadata(pinned(binding["acceptance"]))
    require(acceptance["status"] == "PASS" and acceptance["material_scope"] == (SYNTHETIC if synthetic else REAL)
            and acceptance["production_evidence_authoritative"] is (not synthetic)
            and acceptance["fallback_used"] is False, "COMPONENT_SOURCE_NOT_PRODUCTION_ACCEPTED")
    require(acceptance["normalized_history_sha256"] == binding["history"]["sha256"]
            and acceptance["raw_receipt_references_sha256"] == digest(binding["raw_receipts"]),
            "COMPONENT_NORMALIZATION_BINDING")
    require(acceptance["normalization_owner_sha256_lf"] == owners(), "COMPONENT_NORMALIZATION_OWNER_DRIFT")
    require(_time(acceptance["validated_at"]) <= _time(as_of), "COMPONENT_FUTURE_VALIDATION")
    refs = {}
    for ref in binding["raw_receipts"]:
        require(ref["id"] not in refs and ref["family"] in FAMILIES, "COMPONENT_DUPLICATE_SOURCE_ID")
        body = pinned(ref["raw"])
        receipt = read_metadata(pinned(ref["receipt"]))
        expected_host = "tdcc.com.tw" if ref["family"] == "tdcc" else (
            "twse.com.tw" if ref["market"] == "TWSE" else "tpex.org.tw")
        endpoint = urlparse(receipt["endpoint"])
        require(endpoint.scheme == "https" and (endpoint.hostname == expected_host or
                str(endpoint.hostname).endswith("." + expected_host)), "COMPONENT_SOURCE_ENDPOINT")
        require(receipt["http_status"] == 200 and receipt["final_url"] == receipt["endpoint"]
                and receipt["raw_sha256"] == ref["raw"]["sha256"] and receipt["bytes"] == len(body)
                and receipt["market"] == ref["market"] and receipt["family"] == ref["family"],
                "COMPONENT_RECEIPT_BINDING")
        require(_time(receipt["requested_at"]) <= _time(receipt["observed_at"])
                <= _time(receipt["validated_at"]) <= _time(acceptance["validated_at"]),
                "COMPONENT_SOURCE_TIME_ORDER")
        refs[ref["id"]] = {**ref, "observed_at": receipt["observed_at"]}
    history = read_metadata(pinned(binding["history"]))
    require(history["artifact_kind"] == "RATE_OFFICIAL_COMPONENT_HISTORY_INPUT_V1"
            and history["material_scope"] == acceptance["material_scope"]
            and history["ranking_universe_identity"] == acceptance["ranking_universe_identity"],
            "COMPONENT_HISTORY_ACCEPTANCE_BINDING")
    return history, acceptance, refs


def _finite(value, *, positive=False, nonnegative=False):
    require(type(value) in (int, float) and math.isfinite(value), "COMPONENT_NONFINITE_VALUE")
    require(not positive or value > 0, "COMPONENT_NONPOSITIVE_VALUE")
    require(not nonnegative or value >= 0, "COMPONENT_NEGATIVE_VALUE")


def _history(rows, *, family, symbol, market, target, refs, session_dates, tdcc_periods):
    require(isinstance(rows, list), "COMPONENT_HISTORY_SCHEMA")
    if not rows:
        return "MISSING_REQUIRED_HISTORY", "NO_" + family.upper() + "_HISTORY"
    key = "period_end" if family == "tdcc" else "trade_date"
    dates = [r[key] for r in rows]
    require(dates == sorted(set(dates)) and all(date.fromisoformat(d).isoformat() == d and d <= target for d in dates),
            "COMPONENT_DUPLICATE_FUTURE_OR_UNORDERED_DATE")
    for row in rows:
        ref = refs.get(row.get("evidence_ref"))
        require(ref is not None and ref["family"] == family and ref["market"] == market,
                "COMPONENT_ROW_SOURCE_BINDING")
        require(isinstance(row.get("raw_locator"), str) and bool(row["raw_locator"]), "COMPONENT_ROW_LOCATOR_MISSING")
        require(row.get("symbol") == symbol if family != "benchmark" else
                row.get("benchmark_symbol") == ("TAIEX" if market == "TWSE" else "TPEX"),
                "COMPONENT_ISSUER_OR_BENCHMARK_IDENTITY")
        require(row.get("market") == market, "COMPONENT_MARKET_IDENTITY")
        if family == "stock":
            for field in ("open", "high", "low", "close"):
                _finite(row[field], positive=True)
            for field in ("volume", "turnover"):
                _finite(row[field], nonnegative=True)
            require(row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"],
                    "COMPONENT_OHLC_INVALID")
        elif family == "benchmark":
            _finite(row["close"], positive=True)
        elif family == "institutional":
            for field in ("foreign_net_shares", "investment_trust_net_shares"):
                _finite(row[field])
            _finite(row["close"], positive=True)
            _finite(row["turnover"], nonnegative=True)
        else:
            _finite(row["holder_pct_400"], nonnegative=True)
            require(row["holder_pct_400"] <= 100 and row[key] in tdcc_periods, "COMPONENT_TDCC_PERIOD_INVALID")
    minimum = 5 if family == "tdcc" else 26 if family == "institutional" else 180
    if family != "tdcc":
        require(set(dates).issubset(session_dates), "COMPONENT_WRONG_SESSION_DATE:" + family)
        require(dates[-1] == target, "COMPONENT_WRONG_LATEST_DATE:" + family)
        if len(rows) >= minimum:
            require(dates[-minimum:] == session_dates[-minimum:], "COMPONENT_HISTORY_SESSION_GAP:" + family)
    if len(rows) < minimum:
        return "MISSING_REQUIRED_HISTORY", "INSUFFICIENT_" + family.upper() + "_HISTORY"
    if family == "stock" and sum(r["volume"] for r in rows[-20:]) == 0:
        return "NOT_COMPUTED", "OWNER_VOLUME_DENOMINATOR_ZERO"
    if family == "institutional" and sum(r["turnover"] for r in rows[-20:]) == 0:
        return "NOT_COMPUTED", "OWNER_TURNOVER_DENOMINATOR_ZERO"
    return "PASS", None


def _population(component, members, universe_id, owner_hashes):
    members = sorted(members)
    return {"component_population_id": "rate-component-population-" + digest({
        "component": component, "members": members, "ranking_universe_identity": universe_id,
        "owner_sha256_lf": owner_hashes}), "component_population_count": len(members), "members": members}


def build(universe, *, expected_universe_identity, generated_at, validated_at, evidence_as_of,
          binding=None, trusted_acceptance_sha256=None, synthetic=False):
    owner_hashes = owners()
    stocks, universe_id = exact_universe(universe)
    require(universe_id == expected_universe_identity and (synthetic or universe_id == CONTRACT["universe_identity"]),
            "COMPONENT_EXACT_UNIVERSE_IDENTITY")
    require(_time(generated_at) <= _time(validated_at) <= _time(evidence_as_of) <= _time(now()),
            "COMPONENT_EXECUTION_TIME_ORDER")
    verdicts = {r["symbol"]: {name: {"symbol": r["symbol"], "market": r["market"], "component": name,
        "owner": OWNERS[name], "status": "NOT_EVALUATED", "reason": "PRODUCTION_EVIDENCE_ACQUISITION_REQUIRED",
        "value": None, "observed_at": None, "validated_at": validated_at, "evidence_references": [],
        "ranking_universe_identity": universe_id, "component_population_id": None,
        "source_snapshot_id": None, "calculation_spec_version": STAGE_OPERATIONAL_SPEC_VERSION if name == "Stage" else
        "RATE-PLS-V1.1" if name in ("M7", "MHE") else "RATE-DFCS-V1.0"} for name in COMPONENTS} for r in stocks}
    populations = {name: {"component_population_id": None, "component_population_count": 0, "members": []} for name in COMPONENTS}
    history_populations = {}
    source_binding = None
    if binding is not None:
        history, acceptance, refs = load_sources(binding, trusted_acceptance_sha256=trusted_acceptance_sha256,
                                                 as_of=evidence_as_of, synthetic=synthetic)
        source_binding = deepcopy(binding)
        require(history["ranking_universe_identity"] == universe_id, "COMPONENT_SOURCE_UNIVERSE_MISMATCH")
        require(set(history["issuers"]) == set(verdicts), "COMPONENT_MISSING_OR_EXTRA_ISSUER")
        target = history["trading_date"]
        require(date.fromisoformat(target).isoformat() == target and target <= _time(evidence_as_of).date().isoformat(),
                "COMPONENT_FUTURE_TRADING_DATE")
        sessions = acceptance["verified_sessions"]
        for market in ("TWSE", "TPEX"):
            dates = sessions[market]
            require(len(dates) >= 180 and dates == sorted(set(dates)) and dates[-1] == target
                    and acceptance["latest_official_session"][market] == target,
                    "COMPONENT_LATEST_VERIFIED_SESSION_REQUIRED")
            require(acceptance["session_gate"][market] == "MARKET_SESSION_CONFIRMED", "COMPONENT_SESSION_GATE")
        # Aligned cross-sectional deltas cannot silently use different market sessions.
        require(sessions["TWSE"][-12:] == sessions["TPEX"][-12:], "COMPONENT_CROSS_MARKET_SESSION_ALIGNMENT")
        observed = max((ref["observed_at"] for ref in refs.values()), key=_time)
        require(_time(observed) <= _time(acceptance["validated_at"]) <= _time(validated_at), "COMPONENT_OBSERVATION_TIME_ORDER")
        require(_time(observed) >= _time(target + "T13:30:00+08:00"), "COMPONENT_PRECLOSE_EVIDENCE")
        from scripts.publish_production_source_bundle_latest import validate_freshness
        for market in ("TWSE", "TPEX"):
            for family, key in (("stock", "current_daily_receipt_ids"), ("benchmark", "current_benchmark_receipt_ids")):
                current_ref = refs[acceptance[key][market]]
                require(current_ref["family"] == family and current_ref["market"] == market,
                        "COMPONENT_CURRENT_SOURCE_BINDING")
                current_observed = current_ref["observed_at"]
                require(_time(current_observed) >= _time(target + "T13:30:00+08:00"), "COMPONENT_PRECLOSE_EVIDENCE")
                fresh = validate_freshness({"trading_date": target, "retrieval_timestamp": current_observed},
                    cadence="19:30", trading_date=target, now=_time(evidence_as_of))
                require(fresh["status"] == "PASS", "COMPONENT_STALE_EVIDENCE")
        checks = {}
        for issuer in stocks:
            symbol, market = issuer["symbol"], issuer["market"]
            item = history["issuers"][symbol]
            require(item["market"] == market and set(item["histories"]) == set(FAMILIES), "COMPONENT_ISSUER_MARKET_OR_FAMILY")
            checks[symbol] = {}
            for family in FAMILIES:
                try:
                    checks[symbol][family] = _history(item["histories"][family], family=family, symbol=symbol,
                        market=market, target=target, refs=refs, session_dates=sessions[market], tdcc_periods=acceptance["tdcc_available_periods"])
                    if family in ("stock", "benchmark") and item["histories"][family]:
                        key = "current_daily_receipt_ids" if family == "stock" else "current_benchmark_receipt_ids"
                        require(item["histories"][family][-1]["evidence_ref"] == acceptance[key][market],
                                "COMPONENT_CURRENT_ROW_SOURCE_BINDING")
                except (ValueError, KeyError) as exc:
                    checks[symbol][family] = ("INVALID_EVIDENCE", str(exc))
            for name in COMPONENTS:
                dependencies = ("stock", "benchmark") if name in ("MHE", "RelativeStrength", "Liquidity") else FAMILIES
                used = sorted({r["evidence_ref"] for family in dependencies for r in item["histories"][family]
                               if r.get("evidence_ref") in refs})
                source_observed = max((refs[key]["observed_at"] for key in used), key=_time) if used else None
                verdicts[symbol][name].update(observed_at=observed, source_snapshot_id=acceptance["source_snapshot_id"],
                    evidence_references=[refs[key]["id"] for key in used], trading_date=target)
                verdicts[symbol][name]["observed_at"] = source_observed

        def hs(symbol, family):
            return history["issuers"][symbol]["histories"][family]

        def set_value(symbol, name, value, lineage):
            _finite(value)
            require(0 <= value <= 100, "COMPONENT_OWNER_SCORE_RANGE")
            verdicts[symbol][name].update(status="PASS", reason=None, value=value, owner_lineage=lineage)

        technical = [s for s in verdicts if all(checks[s][f][0] == "PASS" for f in ("stock", "benchmark"))]
        for symbol in verdicts:
            for name in COMPONENTS:
                dependencies = ("stock", "benchmark") if name in ("MHE", "RelativeStrength", "Liquidity") else FAMILIES
                failures = [checks[symbol][f] for f in dependencies if checks[symbol][f][0] != "PASS"]
                if failures:
                    status, reason = next((x for x in failures if x[0] == "INVALID_EVIDENCE"), failures[0])
                    verdicts[symbol][name].update(status=status, reason=reason)
        features, stage_history = {}, {s: [] for s in verdicts}
        if len(technical) >= 20:
            stock_map = {s: hs(s, "stock") for s in technical}
            bench_map = {s: hs(s, "benchmark") for s in technical}
            rotations = build_rotation_feature_histories(stock_map, bench_map, as_of_date=target, sessions=12)
            for session in sessions["TWSE"][-7:]:
                sp = {s: [r for r in stock_map[s] if r["trade_date"] <= session] for s in technical}
                bp = {s: [r for r in bench_map[s] if r["trade_date"] <= session] for s in technical}
                scored = compute_scores([sp[s] for s in technical], benchmark_by_symbol=bp)
                tf = {r["symbol"]: r["technical_features"] for r in scored}
                history_populations[session] = {"technical": _population("technical", technical, universe_id, owner_hashes)}
                institutional = []
                for s in technical:
                    if any(checks[s][f][0] != "PASS" for f in ("institutional", "tdcc")):
                        continue
                    ih = [r for r in hs(s, "institutional") if r["trade_date"] <= session]
                    dh = [r for r in hs(s, "tdcc") if r["period_end"] <= session]
                    try:
                        _, required = select_required_period_union([session], acceptance["tdcc_available_periods"])
                        require([r["period_end"] for r in dh[-5:]] == required[session], "COMPONENT_WRONG_TDCC_PERIOD")
                        require(len(ih) >= 20 and ih[-1]["trade_date"] == session, "COMPONENT_INSTITUTIONAL_HISTORY_SHORT")
                    except ValueError as exc:
                        if session == target:
                            for name in ("M7", "SmartMoney", "Rotation", "Stage"):
                                verdicts[s][name].update(status="MISSING_REQUIRED_HISTORY", reason=str(exc))
                        continue
                    fr = {field: [r for r in values if r["trade_date"] <= session][-6:] for field, values in rotations[s].items()}
                    institutional.append({"symbol": s, "institutional_history": deepcopy(ih), "tdcc_history": deepcopy(dh), **fr})
                history_populations[session]["institutional"] = _population("institutional", [r["symbol"] for r in institutional], universe_id, owner_hashes)
                calculated = calculate_institutional_rotation(institutional) if len(institutional) >= 20 else []
                for item in calculated:
                    s = item["symbol"]
                    m7_inputs = {k: tf[s][k] for k in ("PT", "PV", "MO", "RS")} | {k: item[k] for k in ("FI", "IT", "LH")}
                    m7 = calculate_m7(m7_inputs)
                    mhe = calculate_mhe({k: tf[s][k] for k in ("H5", "H20", "H60", "H120")})
                    tr = technical_record(sp[s], bp[s])
                    from .stage_evidence import rotation_class
                    stage_history[s].append({"trade_date": session, "M7": m7["m7_score"], "MHE": mhe["mhe_score"],
                        "Rotation": item["Rotation"], "RotationClass": rotation_class(item["Rotation"]),
                        "technical_record": tr, "technical_features": tf[s], "close": sp[s][-1]["close"],
                        "stock_low_values": [{"trade_date": r["trade_date"], "low": r["low"]} for r in sp[s]],
                        "calculation_spec_version": STAGE_OPERATIONAL_SPEC_VERSION,
                        "source_type": "DERIVED_FROM_HISTORICAL_FEATURE_REPLAY"})
                    if session == target:
                        set_value(s, "M7", m7["m7_score"], m7)
                        set_value(s, "Rotation", item["Rotation"], item["feature_lineage"])
                        smart = calculate_smart_money(item["SmartMoney_inputs"])
                        set_value(s, "SmartMoney", smart["smart_money_score"], smart)
                if session == target:
                    features = tf
                    for s in technical:
                        mhe = calculate_mhe({k: tf[s][k] for k in ("H5", "H20", "H60", "H120")})
                        set_value(s, "MHE", mhe["mhe_score"], mhe)
                        for name in ("RelativeStrength", "Liquidity"):
                            set_value(s, name, tf[s][name], next(r["feature_evidence"][name] for r in scored if r["symbol"] == s))
        for s in technical:
            if len(stage_history[s]) == 7:
                latest = stage_history[s][-1]
                prior = history.get("prior_stage_state")
                authority = acceptance.get("stage_reconstruction_authority_id")
                if not authority and not (prior and prior.get("state_id") and prior.get("symbols", {}).get(s, {}).get("stage_current")):
                    verdicts[s]["Stage"].update(status="NOT_COMPUTED", reason="STAGE_PRIOR_OR_RECONSTRUCTION_AUTHORITY_REQUIRED")
                    continue
                stage = build_production_stage_evidence(symbol=s, stock_history=hs(s, "stock"),
                    technical_record=latest["technical_record"], technical_features=features[s],
                    m7_score=latest["M7"], mhe_score=latest["MHE"], rotation_score=latest["Rotation"],
                    prior_state=deepcopy(prior), input_snapshot_id=acceptance["source_snapshot_id"],
                    feature_history=stage_history[s], control_state_id=authority)
                set_value(s, "Stage", stage["stage_normalized_score"], stage)
        for name in COMPONENTS:
            members = [s for s in verdicts if verdicts[s][name]["status"] == "PASS"]
            populations[name] = _population(name, members, universe_id, owner_hashes)
            for s in verdicts:
                v = verdicts[s][name]
                v["component_population_id"] = populations[name]["component_population_id"]
                if v["status"] == "NOT_EVALUATED":
                    v.update(status="NOT_COMPUTED", reason="EXISTING_OWNER_MINIMUM_POPULATION_OR_HISTORY_NOT_SATISFIED")
    counts = {name: dict(Counter(verdicts[s][name]["status"] for s in verdicts)) for name in COMPONENTS}
    core = {"artifact_kind": KIND, "contract_version": CONTRACT["version"], "material_scope": SYNTHETIC if synthetic else
        REAL if binding else "MISSING_PRODUCTION_EVIDENCE_INVENTORY_ONLY",
        "ranking_universe_identity": universe_id, "ranking_universe_count": len(stocks), "universe": stocks,
        "source_binding": source_binding, "owner_sha256_lf": owner_hashes, "populations": populations,
        "history_populations": history_populations, "counts": counts,
        "issuers": [{**r, "components": verdicts[r["symbol"]]} for r in stocks], "governance": deepcopy(CONTRACT["governance"])}
    content = digest(core)
    return {"artifact_kind": KIND, "artifact_id": "rate-full-market-components-" + content, "content_sha256": content,
        "core": core, "generated_at": generated_at, "validated_at": validated_at, "evidence_as_of": evidence_as_of,
        "source_status": "PRODUCTION_EVIDENCE_ACQUISITION_REQUIRED" if binding is None else "SOURCE_REPLAY_VALIDATED"}


def verify(bundle, universe, *, expected_universe_identity, as_of, trusted_acceptance_sha256=None, synthetic=False):
    require(digest(bundle["core"]) == bundle["content_sha256"] and bundle["artifact_id"] ==
            "rate-full-market-components-" + bundle["content_sha256"], "COMPONENT_ARTIFACT_IDENTITY_TAMPER")
    require(_time(bundle["validated_at"]) <= _time(bundle["evidence_as_of"]) <= _time(as_of), "COMPONENT_FUTURE_ARTIFACT")
    rebuilt = build(universe, expected_universe_identity=expected_universe_identity,
        generated_at=bundle["generated_at"], validated_at=bundle["validated_at"], evidence_as_of=as_of,
        binding=bundle["core"]["source_binding"], trusted_acceptance_sha256=trusted_acceptance_sha256, synthetic=synthetic)
    require(rebuilt["core"] == bundle["core"] and rebuilt["content_sha256"] == bundle["content_sha256"], "COMPONENT_COLD_REPLAY_MISMATCH")
    return True


def readiness_preview(bundle, fundamental, *, trusted_file_sha256, synthetic=False):
    """Read accepted Fundamental verdicts without calling its calculation owner."""
    body = pinned({"path": str(fundamental), "sha256": trusted_file_sha256})
    fb = read_metadata(body)
    require(digest(fb["core"]) == fb["content_sha256"], "COMPONENT_FUNDAMENTAL_IDENTITY")
    if not synthetic:
        require(fb["artifact_kind"] == FUNDAMENTAL_CONTRACT["artifact_kind"]
                and fb["core"]["source_binding"]["source"] == FUNDAMENTAL_CONTRACT["accepted_source"]
                and fb["core"]["owner_code_sha256_lf"] == FUNDAMENTAL_CONTRACT["owner_code_sha256_lf"],
                "COMPONENT_FUNDAMENTAL_ACCEPTED_BINDING")
    else:
        require(bundle["core"]["material_scope"] == SYNTHETIC, "COMPONENT_SYNTHETIC_PREVIEW_SCOPE")
    require(fb["core"]["universe_identity"] == bundle["core"]["ranking_universe_identity"], "COMPONENT_FUNDAMENTAL_UNIVERSE")
    original = {r["symbol"]: r for r in fb["core"]["issuers"]}
    require(len(original) == 1978 and set(original) == {r["symbol"] for r in bundle["core"]["issuers"]}, "COMPONENT_FUNDAMENTAL_ISSUERS")
    results = []
    for row in bundle["core"]["issuers"]:
        f = original[row["symbol"]]
        require(f["market"] == row["market"], "COMPONENT_FUNDAMENTAL_MARKET")
        ready = {name for name, v in row["components"].items() if v["status"] == "PASS"}
        if f["status"] == "PASS":
            ready.add("Fundamental")
        results.append({"symbol": row["symbol"], "market": row["market"], "fundamental_status": f["status"],
            "fundamental_component_population_id": f["population_id"], "ranking_universe_identity": bundle["core"]["ranking_universe_identity"],
            "kinds": {kind: {"input_ready": set(required) <= ready, "missing": sorted(set(required) - ready),
                    "score": None, "rank": None, "authorized": False} for kind, required in RANK_INPUTS.items()}})
    return {"issuer_count": len(results), "counts": {kind: sum(r["kinds"][kind]["input_ready"] for r in results) for kind in RANK_INPUTS},
        "fundamental_population_id": fb["core"]["population_id"], "fundamental_recomputed": False, "issuers": results}


def save(output, bundle):
    from scripts.run_prospective_provider_activation import external
    output = external(Path(output))
    require(not Path(output).exists(), "COMPONENT_OUTPUT_MUST_BE_NEW")
    return put_bytes(output, "RATE_FULL_MARKET_COMPONENT_EVIDENCE_V1.json", canonical(bundle))


def acquisition_plan(universe, *, expected_universe_identity, execution_head):
    """An exact four-target discovery proposal; never an acquisition command.

    History requests cannot be enumerated truthfully until official session and
    TDCC available-period evidence is accepted. Do not infer either calendar.
    """
    _, uid = exact_universe(universe)
    require(uid == expected_universe_identity, "COMPONENT_PLAN_UNIVERSE")
    from .sources.twse import BASE as TWSE_BASE
    from .sources.tpex import CURRENT_DAILY_ENDPOINT, BENCHMARK_ENDPOINT, HISTORICAL_ENDPOINT, INDEX_HISTORY_ENDPOINT, INSTITUTIONAL_DAILY_ENDPOINT
    from .sources.tdcc_historical import TDCC_HISTORICAL_PAGE
    targets = [("TWSE", "benchmark", TWSE_BASE + "/exchangeReport/MI_INDEX"),
               ("TWSE", "market_daily", TWSE_BASE + "/exchangeReport/STOCK_DAY_ALL"),
               ("TPEX", "benchmark", BENCHMARK_ENDPOINT), ("TPEX", "market_daily", CURRENT_DAILY_ENDPOINT)]
    entries = [{"ordinal": i, "market": market, "source": market + " Official", "product": product,
                "endpoint": endpoint, "method": "GET", "maximum_requests": 1, "timeout_seconds": 30}
               for i, (market, product, endpoint) in enumerate(targets, 1)]
    core = {"artifact_kind": "RATE_FULL_MARKET_COMPONENT_ACQUISITION_PROPOSAL_V1",
        "status": "PENDING_CONTROL_CENTER_AUTHORIZATION", "execution_head": execution_head,
        "ranking_universe_identity": uid, "ranking_universe_count": 1978,
        "scope": "OFFICIAL_CURRENT_SESSION_DISCOVERY_ONLY_NOT_FULL_HISTORY_ACQUISITION",
        "entries": entries, "expected_requests": 4, "maximum_requests": 4,
        "credentials": "Official public products; no token requested or read",
        "minimum_interval_seconds": 13, "sequential": True, "single_writer": True,
        "retry": 0, "fallback_allowed": False, "redirect_allowed": False,
        "expected_pacing_seconds": 39, "maximum_http_timeout_seconds": 120,
        "duration_note": "39 seconds minimum inter-dispatch pacing plus four bounded HTTP calls and local validation; not a completion guarantee",
        "immutable_evidence": "Pre-dispatch intent; exact raw bytes and receipt in content-addressed objects; timestamp/session/endpoint/hash binding; unknown outcome STOP; no overwrite",
        "stop_conditions": ["HTTP_FAILURE", "SCHEMA_FAILURE", "SOURCE_IDENTITY_FAILURE", "UNKNOWN_OUTCOME", "HASH_MISMATCH"],
        "history_acquisition": {"status": "NOT_EXECUTABLE_PENDING_VERIFIED_CALENDAR_PERIODS_AND_AUTHORIZATION",
            "expected_requests": None, "maximum_requests": None,
            "blocking_inputs": ["latest official EOD session per market", "180 verified session dates per market",
                "exact 26 institutional sessions", "official TDCC period list and five-period union for seven Stage sessions",
                "accepted reusable historical raw/receipt inventory", "no-fallback single-attempt transport binding"],
            "request_enumeration": "Reuse verified materials first. Enumerate each remaining symbol/month, benchmark/month, market/session, and symbol/TDCC-period exactly once; separately include required official form/schema initialization.",
            "stock_monthly_endpoints": {"TWSE": "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date={YYYYMM}01&stockNo={symbol}&response=json", "TPEX": HISTORICAL_ENDPOINT},
            "benchmark_monthly_endpoints": {"TWSE": "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={YYYYMM}01&response=json", "TPEX": INDEX_HISTORY_ENDPOINT},
            "institutional_daily_endpoints": {"TWSE": "https://www.twse.com.tw/rwd/zh/fund/T86?date={YYYYMMDD}&selectType=ALLBUT0999&response=json", "TPEX": INSTITUTIONAL_DAILY_ENDPOINT},
            "tdcc_endpoint": TDCC_HISTORICAL_PAGE,
            "existing_transport_caution": "Some existing history transports implement retries or official-route fallback. They MUST NOT be invoked unchanged under a zero-retry/no-fallback authorization; separately bind a reviewed one-attempt transport before execution.",
            "contains_no_fundamental_or_intraday_requests": True},
        "execution_allowed": False, "ranking_authorized": False, "production_publication_allowed": False}
    sha = digest(core)
    return {"plan_id": "rate-component-acquisition-proposal-" + sha, "content_sha256": sha, "core": core}
