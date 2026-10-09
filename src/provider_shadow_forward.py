"""Observed-forward, immutable hash-chain events. No acquisition or formal scoring."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import math
from pathlib import Path
from statistics import mean, median, stdev

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_candidate import _canonical, _time, _decimal
from .provider_eps_dispatch import exclusive_scan
from .provider_eps_metadata import read_metadata
from .provider_financial_features import hash_object, instant, within_git_checkout
from .provider_fundamental_shadow import SCORE

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/contracts/RATE_PROVIDER_SHADOW_FORWARD_VALIDATION_V1.json"
SPEC = read_metadata(CONTRACT_PATH.read_bytes())
KINDS = ("SHADOW_FORWARD_SNAPSHOT_LEDGER", "SHADOW_FORWARD_RETURN_LEDGER", "SHADOW_FORWARD_EVALUATION_LEDGER")


def number(value):
    require(not isinstance(value, bool), "FORWARD_BOOL_NOT_NUMBER")
    result = float(_decimal(str(value) if isinstance(value, float) else value))
    require(math.isfinite(result), "FORWARD_NONFINITE")
    return result


def correlation(xs, ys):
    require(len(xs) == len(ys), "FORWARD_PAIR_COUNT")
    if len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    xx, yy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    return max(-1.0, min(1.0, sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(xx * yy))) if xx and yy else None


def ranks(values):
    ordered = sorted(enumerate(values), key=lambda p: p[1])
    result, index = [0.0] * len(values), 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        for position, _ in ordered[index:end]:
            result[position] = (index + 1 + end) / 2
        index = end
    return result


def spearman(xs, ys):
    return correlation(ranks(xs), ranks(ys))


def members(rows):
    scored = [r for r in rows if r["score"] is not None]
    n = len(scored)
    require(n >= 20, "FORWARD_SCORED_TOO_SMALL")
    result = {k: [] for k in ("Top10", "Top20", "Middle", "Bottom20", "Bottom10")}
    for row in scored:
        score = row["score"]
        top = 1 + sum(r["score"] > score for r in scored)
        bottom = 1 + sum(r["score"] < score for r in scored)
        require(top == row["rank"], "FORWARD_SHADOW_RANK_MISMATCH")
        tags = []
        if top <= (n + 9) // 10:
            tags.append("Top10")
        if top <= (n + 4) // 5:
            tags.append("Top20")
        if bottom <= (n + 9) // 10:
            tags.append("Bottom10")
        if bottom <= (n + 4) // 5:
            tags.append("Bottom20")
        if "Top20" not in tags and "Bottom20" not in tags:
            tags.append("Middle")
        for tag in tags:
            result[tag].append(row["symbol"])
    return {k: sorted(v) for k, v in result.items()}


def baseline(shadow, *, sealed_at, effective_at, execution_binding, source_pin, require_fresh=True):
    sealed, effective = _time(sealed_at), _time(effective_at)
    require(effective <= sealed <= _time(instant()), "FORWARD_FABRICATED_TIME")
    require(not require_fresh or (_time(instant()) - sealed).total_seconds() <= 5, "FORWARD_BASELINE_BACKFILL_FORBIDDEN")
    available = _time(shadow["execution"]["shadow_available_at"])
    require(available <= sealed, "FORWARD_SHADOW_NOT_AVAILABLE")
    core = shadow["core"]
    rows = [{"symbol": r["symbol"], "market": r["market"], "score": r[SCORE], "rank": r["shadow_rank"],
        "unscored_reasons": deepcopy(r["unscored_reasons"])} for r in sorted(core["companies"], key=lambda c: c["symbol"])]
    require(len({r["symbol"] for r in rows}) == len(rows), "FORWARD_POPULATION_DUPLICATE")
    for row in rows:
        require(row["market"] in ("TWSE", "TPEX") and (row["score"] is None) == (row["rank"] is None), "FORWARD_POPULATION_INVALID")
        if row["score"] is not None:
            require(0 <= number(row["score"]) <= 100 and type(row["rank"]) is int, "FORWARD_SCORE_INVALID")
    observation_times = [_time(f["input_observed_at_max"]) for r in core["companies"]
        for f in r["features"].values() if f.get("input_observed_at_max") is not None]
    require(observation_times and max(observation_times) <= available, "FORWARD_SOURCE_TIME_INVALID")
    body = {"feature_content_sha256": core["feature_content_sha256"], "shadow_content_sha256": shadow["content_sha256"],
        "shadow_package_sha256": shadow["package_sha256"], "population_id": core["populations"]["A_COMPLETE_INPUT"]["population_id"],
        "universe_id": hash_object([{k: r[k] for k in ("symbol", "market")} for r in rows]),
        "shadow_available_at": shadow["execution"]["shadow_available_at"], "source_observed_at_max": max(observation_times).isoformat() if observation_times else None,
        "sealed_at": sealed_at, "contract_effective_at": effective_at,
        "forward_available_at": max(available, sealed, effective).isoformat(), "execution_head": execution_binding["head_sha"],
        "execution_binding": execution_binding, "source_shadow_execution": shadow["execution"]["execution_code_binding"],
        "source_pin": source_pin, "contract": SPEC, "contract_sha256": hash_object(SPEC), "companies": rows,
        "groups": members(rows), "historical_pit_status": "UNPROVEN", "validation_basis": "OBSERVED_FORWARD_ONLY",
        "decision_eligible": False, "production_eligible": False}
    body["shadow_snapshot_id"] = "shadow-forward-snapshot-" + hash_object(body)
    return body


def validate_baseline(snapshot):
    require(snapshot["shadow_snapshot_id"] == "shadow-forward-snapshot-" + hash_object({k: v for k, v in snapshot.items() if k != "shadow_snapshot_id"}), "FORWARD_SNAPSHOT_IDENTITY_TAMPERED")
    require(snapshot["contract"] == SPEC and snapshot["contract_sha256"] == hash_object(SPEC), "FORWARD_CONTRACT_CHANGED")
    require(snapshot["groups"] == members(snapshot["companies"]), "FORWARD_GROUP_TAMPERED")
    require(_time(snapshot["forward_available_at"]) == max(_time(snapshot[k]) for k in ("shadow_available_at", "sealed_at", "contract_effective_at")) <= _time(instant()), "FORWARD_TIME_TAMPERED")
    require(snapshot["universe_id"] == hash_object([{k: r[k] for k in ("symbol", "market")} for r in snapshot["companies"]]), "FORWARD_UNIVERSE_TAMPERED")


def heads(root):
    return {kind: (replay_chain(root, kind)[-1]["event_sha256"] if replay_chain(root, kind) else None) for kind in KINDS}


def replay_chain(root, kind):
    require(kind in KINDS, "FORWARD_LEDGER_KIND_INVALID")
    records, previous = [], None
    for index, path in enumerate(sorted((Path(root) / kind).glob("*.json"))):
        event = read_metadata(path.read_bytes())
        require(event["kind"] == kind and event["sequence"] == index and event["previous_sha256"] == previous and
            event["event_sha256"] == hash_object({k: v for k, v in event.items() if k != "event_sha256"}) and
            path.name == f"{index:08d}-{event['event_sha256']}.json", "FORWARD_LEDGER_CHAIN_TAMPERED")
        require(_time(event["recorded_at"]) <= _time(instant()), "FORWARD_EVENT_FUTURE_TIME")
        if records:
            require(_time(records[-1]["recorded_at"]) <= _time(event["recorded_at"]), "FORWARD_LEDGER_TIME_REGRESSION")
        records.append(event)
        previous = event["event_sha256"]
    return records


def append_event(root, kind, payload, *, recorded_at=None):
    records = replay_chain(root, kind)
    event = {"kind": kind, "sequence": len(records), "previous_sha256": records[-1]["event_sha256"] if records else None,
        "recorded_at": recorded_at or instant(), "payload": payload}
    require(_time(event["recorded_at"]) <= _time(instant()) and (not records or _time(event["recorded_at"]) >= _time(records[-1]["recorded_at"])), "FORWARD_APPEND_TIME_REGRESSION")
    event["event_sha256"] = hash_object(event)
    path = Path(root) / kind / f"{len(records):08d}-{event['event_sha256']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_canonical(event) + b"\n")
    return event


def check_heads(root, expected):
    require(set(expected) == set(KINDS) and heads(root) == expected, "FORWARD_TRUSTED_HEAD_MISMATCH_OR_TRUNCATION")


def verify(root, expected):
    check_heads(root, expected)
    snapshots = [e["payload"] for e in replay_chain(root, KINDS[0])]
    ids = {s["shadow_snapshot_id"] for s in snapshots}
    require(len(ids) == len(snapshots), "FORWARD_DUPLICATE_SNAPSHOT")
    for s in snapshots:
        validate_baseline(s)
    terminal, entry_by_symbol, previous_rows, verified_prices = {}, {}, {}, {}
    for event in replay_chain(root, KINDS[1]):
        payload = event["payload"]
        require(payload["shadow_snapshot_id"] in ids, "FORWARD_RETURN_ORPHAN")
        snapshot = next(s for s in snapshots if s["shadow_snapshot_id"] == payload["shadow_snapshot_id"])
        if payload["price_pin"] is not None:
            from .provider_shadow_forward_prices import load_prices
            book = load_prices(payload["price_pin"], as_of=event["recorded_at"], available_at=snapshot["forward_available_at"])
            verified_prices.update({hash_object(p["reference"]): p for p in book["prices"].values()})
        else:
            book = None
        require(len(payload["returns"]) == len(snapshot["companies"]), "FORWARD_COMPANY_DROPPED")
        require(payload["horizon"] in SPEC["horizons"] and {r["symbol"] for r in payload["returns"]} == {r["symbol"] for r in snapshot["companies"]}, "FORWARD_RETURN_POPULATION_CHANGED")
        for row in payload["returns"]:
            require(row["market"] == next(r["market"] for r in snapshot["companies"] if r["symbol"] == row["symbol"]), "FORWARD_RETURN_MARKET_CHANGED")
            key = (payload["shadow_snapshot_id"], row["symbol"], payload["horizon"])
            require(key not in terminal or terminal[key] == row, "FORWARD_DUPLICATE_FINALIZATION_OR_REWRITE")
            require(row["status"] in ("PENDING", "FINALIZED", "FAIL_CLOSED"), "FORWARD_RETURN_STATUS_INVALID")
            if row["status"] in ("FINALIZED", "FAIL_CLOSED"):
                terminal[key] = row
            entry_key = key[:2]
            if row["entry_price"] is not None:
                identity = (row["entry_price_date"], row["entry_price"], row["entry_price_reference"])
                require(entry_key not in entry_by_symbol or entry_by_symbol[entry_key] == identity, "FORWARD_ENTRY_VERSION_CHANGED")
                entry_by_symbol[entry_key] = identity
                require(_time(row["entry_close_at"]) > _time(snapshot["forward_available_at"]), "FORWARD_ENTRY_BACKFILLED")
            if row["status"] == "FINALIZED":
                require(row["entry_price"] is not None and row["exit_price"] is not None and len(row["price_path"]) == payload["horizon"] + 1 and
                    row["return_value"] == number(row["exit_price"]) / number(row["entry_price"]) - 1 and
                    _time(row["exit_close_at"]) <= _time(event["recorded_at"]), "FORWARD_FINAL_RETURN_INVALID")
                require(book is not None, "FORWARD_PRICE_PIN_REQUIRED")
                sessions = [s for s in book["sessions"][row["market"]] if _time(s["close_at"]) > _time(snapshot["forward_available_at"])]
                require(len(sessions) > payload["horizon"] and [p["date"] for p in row["price_path"]] == [s["date"] for s in sessions[:payload["horizon"] + 1]] and
                    row["entry_price_date"] == sessions[0]["date"] and row["exit_price_date"] == sessions[payload["horizon"]]["date"], "FORWARD_TRADING_OFFSET_TAMPERED")
            for price in ([{"reference": row["entry_price_reference"], "close": row["entry_price"]}] if row["entry_price_reference"] else []) + row["price_path"]:
                from .provider_shadow_forward_prices import verify_reference
                verify_reference(price["reference"])
                require(hash_object(price["reference"]) in verified_prices and verified_prices[hash_object(price["reference"])]["close"] == price["close"], "FORWARD_PRICE_VALUE_NOT_REPLAYED")
        state_key = (payload["shadow_snapshot_id"], payload["horizon"])
        require(state_key not in previous_rows or previous_rows[state_key] != payload["returns"], "FORWARD_DUPLICATE_FINALIZATION")
        previous_rows[state_key] = payload["returns"]
    for e in replay_chain(root, KINDS[2]):
        if e["payload"].get("kind") != "SOURCE_INTEGRITY_FAILURE":
            require(e["payload"]["shadow_snapshot_id"] in ids, "FORWARD_EVALUATION_ORPHAN")
    return {"snapshots": len(snapshots), "heads": expected, "terminal_company_horizons": len(terminal), "status": "PASS"}


def initial_returns(snapshot, horizon):
    return {"shadow_snapshot_id": snapshot["shadow_snapshot_id"], "horizon": horizon, "price_pin": None,
        "returns": [{"symbol": r["symbol"], "market": r["market"], "return_horizon": horizon, "status": "PENDING",
            "reason": "AWAITING_POST_SEAL_OFFICIAL_ENTRY_AND_VERIFIED_SESSIONS", "entry_price_date": None, "entry_price": None,
            "entry_close_at": None, "entry_price_reference": None, "exit_price_date": None, "exit_price": None,
            "exit_close_at": None, "price_source": r["market"] + "_STOCK_DAY", "price_snapshot_hash": None,
            "price_path": [], "return_value": None} for r in snapshot["companies"]]}


def create_baseline(root, snapshot, expected):
    root = Path(root).resolve()
    require(not within_git_checkout(root) and not any(p.casefold() in {"production", "latest", "state", "portfolio", "ledger"} for p in root.parts), "FORWARD_EXTERNAL_CANDIDATE_ROOT_REQUIRED")
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_scan(root):
        check_heads(root, expected)
        validate_baseline(snapshot)
        previous = [e["payload"] for e in replay_chain(root, KINDS[0])]
        same = [s for s in previous if s["shadow_package_sha256"] == snapshot["shadow_package_sha256"]]
        require(not same or same[0] == snapshot, "FORWARD_SAME_SHADOW_CANNOT_CREATE_FAKE_NEW_SNAPSHOT")
        if not same:
            require(0 <= (_time(instant()) - _time(snapshot["sealed_at"])).total_seconds() <= 5, "FORWARD_BASELINE_BACKFILL_FORBIDDEN")
            require(not previous or _time(snapshot["sealed_at"]) > _time(previous[-1]["sealed_at"]), "FORWARD_SNAPSHOT_BACKFILL")
            append_event(root, KINDS[0], snapshot)
        for horizon in SPEC["horizons"]:
            existing = [e for e in replay_chain(root, KINDS[1]) if (e["payload"]["shadow_snapshot_id"], e["payload"]["horizon"]) == (snapshot["shadow_snapshot_id"], horizon)]
            if not existing:
                pending = initial_returns(snapshot, horizon)
                append_event(root, KINDS[1], pending)
                append_event(root, KINDS[2], evaluate(snapshot, pending))
        return verify(root, heads(root))


def resolve_returns(snapshot, horizon, book, *, as_of, prior_rows):
    require(horizon in SPEC["horizons"] and _time(snapshot["sealed_at"]) <= _time(as_of) <= _time(instant()), "FORWARD_ASOF_INVALID")
    old = {r["symbol"]: r for r in prior_rows}
    require(set(old) == {r["symbol"] for r in snapshot["companies"]}, "FORWARD_PRIOR_POPULATION_CHANGED")
    rows = []
    for company in snapshot["companies"]:
        symbol, market = company["symbol"], company["market"]
        row = deepcopy(old[symbol])
        if row["status"] != "PENDING":
            rows.append(row)
            continue
        sessions = [s for s in book["sessions"][market] if _time(s["close_at"]) > _time(snapshot["forward_available_at"]) and _time(s["close_at"]) <= _time(as_of)]
        if not sessions:
            rows.append(row)
            continue
        entry_session = sessions[0]
        entry = book["prices"].get((symbol, entry_session["date"]))
        row.update(entry_price_date=entry_session["date"], entry_close_at=entry_session["close_at"], price_snapshot_hash=book["manifest_sha256"])
        if entry is None:
            row.update(status="FAIL_CLOSED", reason="ENTRY_PRICE_MISSING_SUSPENSION_DELISTING_OR_UNKNOWN_NOT_IMPUTED")
            rows.append(row)
            continue
        require(entry["reference"]["market"] == market, "FORWARD_PRICE_MARKET_IDENTITY")
        if row["entry_price"] is not None:
            require(row["entry_price_date"] == old[symbol]["entry_price_date"] and entry["close"] == row["entry_price"], "FORWARD_ENTRY_REVISED")
        else:
            row.update(entry_price=entry["close"], entry_price_reference=entry["reference"])
        if len(sessions) <= horizon:
            row.update(reason="HORIZON_NOT_MATURE")
            rows.append(row)
            continue
        required = sessions[:horizon + 1]
        path = [book["prices"].get((symbol, s["date"])) for s in required]
        row.update(exit_price_date=required[-1]["date"], exit_close_at=required[-1]["close_at"])
        if any(p is None for p in path):
            row.update(status="FAIL_CLOSED", reason="REQUIRED_DAILY_PATH_MISSING_SUSPENSION_DELISTING_OR_UNKNOWN_NOT_IMPUTED")
        else:
            require(all(p["reference"]["market"] == market for p in path), "FORWARD_PRICE_MARKET_IDENTITY")
            row.update(status="FINALIZED", reason=None, exit_price=path[-1]["close"], exit_price_reference=path[-1]["reference"],
                price_path=[{**p, "date": s["date"]} for p, s in zip(path, required)],
                return_value=number(path[-1]["close"]) / number(row["entry_price"]) - 1)
        rows.append(row)
    return {"shadow_snapshot_id": snapshot["shadow_snapshot_id"], "horizon": horizon, "price_pin": book["pin"], "returns": rows}


def metrics(rows, expected):
    valid = [r for r in rows if r["status"] == "FINALIZED"]
    xs = [r["return_value"] for r in valid]
    curve = [mean(number(r["price_path"][i]["close"]) / number(r["entry_price"]) for r in valid) for i in range(len(valid[0]["price_path"]))] if valid else []
    peak, drawdown = 1.0, 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    return {"mean_return": mean(xs) if xs else None, "median_return": median(xs) if xs else None,
        "win_rate": sum(v > 0 for v in xs) / len(xs) if xs else None, "volatility": stdev(xs) if len(xs) > 1 else None,
        "max_drawdown": drawdown if xs else None, "sample_count": len(xs), "expected_count": expected,
        "coverage": len(xs) / expected if expected else None, "fail_closed_count": sum(r["status"] == "FAIL_CLOSED" for r in rows),
        "pending_count": sum(r["status"] == "PENDING" for r in rows), "metric_definitions": hash_object(SPEC)}


def evaluate(snapshot, returns):
    require(returns["shadow_snapshot_id"] == snapshot["shadow_snapshot_id"], "FORWARD_EVALUATION_IDENTITY")
    rows, companies = returns["returns"], snapshot["companies"]
    require({r["symbol"] for r in rows} == {r["symbol"] for r in companies} and len(rows) == len(companies), "FORWARD_EVALUATION_POPULATION")
    groups = {k: metrics([r for r in rows if r["symbol"] in set(symbols)], len(symbols)) for k, symbols in snapshot["groups"].items()}
    scored = {r["symbol"]: r for r in companies if r["score"] is not None}
    valid = [r for r in rows if r["status"] == "FINALIZED" and r["symbol"] in scored]
    def ic(rs):
        return spearman([scored[r["symbol"]]["score"] for r in rs], [r["return_value"] for r in rs])
    spreads = {}
    for fraction in (10, 20):
        top, bottom = groups[f"Top{fraction}"]["mean_return"], groups[f"Bottom{fraction}"]["mean_return"]
        spreads[f"Top{fraction}_minus_Bottom{fraction}"] = top - bottom if top is not None and bottom is not None else None
    scored_stats = metrics([r for r in rows if r["symbol"] in scored], len(scored))
    unscored_stats = metrics([r for r in rows if r["symbol"] not in scored], len(companies) - len(scored))
    sm, um = scored_stats["mean_return"], unscored_stats["mean_return"]
    loo = [{"excluded_symbol_for_diagnostic_only": r["symbol"], "rank_ic": ic([q for q in valid if q["symbol"] != r["symbol"]]),
        "spreads": {f"Top{k}_minus_Bottom{k}": (mean([q["return_value"] for q in valid if q["symbol"] in snapshot["groups"][f"Top{k}"] and q != r]) -
            mean([q["return_value"] for q in valid if q["symbol"] in snapshot["groups"][f"Bottom{k}"] and q != r]))
            if any(q["symbol"] in snapshot["groups"][f"Top{k}"] and q != r for q in valid) and any(q["symbol"] in snapshot["groups"][f"Bottom{k}"] and q != r for q in valid) else None for k in (10, 20)}} for r in valid]
    middle_order = [groups[k]["mean_return"] for k in ("Bottom20", "Middle", "Top20")]
    overlap = sorted(set(snapshot["groups"]["Top20"]) & set(snapshot["groups"]["Bottom20"]))
    return {"shadow_snapshot_id": snapshot["shadow_snapshot_id"], "horizon": returns["horizon"], "groups": groups,
        "rank_ic": ic(valid), "rank_ic_sample_count": len(valid), "spreads": spreads,
        "monotonicity_bottom_middle_top": all(a <= b for a, b in zip(middle_order, middle_order[1:])) if all(x is not None for x in middle_order) else None,
        "boundary_tie_overlap": overlap, "scored_population_returns": scored_stats, "unscored_population_returns": unscored_stats,
        "scored_minus_unscored_mean": sm - um if sm is not None and um is not None else None,
        "outlier_diagnostics": {"returns_extremes": [{"symbol": r["symbol"], "return": r["return_value"]} for r in sorted(valid, key=lambda r: (r["return_value"], r["symbol"]))[:3] + sorted(valid, key=lambda r: (-r["return_value"], r["symbol"]))[:3]], "leave_one_out": loo, "excluded_from_primary_analysis": []},
        "status": "PENDING" if any(r["status"] == "PENDING" for r in rows) else "FINALIZED",
        "valid_observed_forward_snapshot": ic(valid) is not None and not overlap and not any(r["status"] == "PENDING" for r in rows),
        "missing_policy_unchanged": True, "decision_eligible": False, "production_eligible": False}


def stability(previous, current):
    a = {r["symbol"]: r for r in previous["companies"] if r["score"] is not None}
    b = {r["symbol"]: r for r in current["companies"] if r["score"] is not None}
    common = sorted(set(a) & set(b))
    sets = {}
    for k in ("Top10", "Top20"):
        old, new = set(previous["groups"][k]), set(current["groups"][k])
        retention = len(old & new) / len(old) if old else None
        sets[k] = {"retention": retention, "one_way_turnover": 1 - retention if retention is not None else None,
            "removed": sorted(old - new), "added": sorted(new - old)}
    return {"previous_snapshot_id": previous["shadow_snapshot_id"], "current_snapshot_id": current["shadow_snapshot_id"], "common_count": len(common),
        "score_correlation": correlation([a[s]["score"] for s in common], [b[s]["score"] for s in common]),
        "rank_correlation": spearman([a[s]["rank"] for s in common], [b[s]["rank"] for s in common]), "groups": sets}


def gates(evaluations):
    result = {}
    for gate, horizon in zip(("A", "B", "C"), SPEC["horizons"]):
        latest = {}
        for e in evaluations:
            if e["horizon"] == horizon:
                latest[e["shadow_snapshot_id"]] = e
        valid = [e for e in latest.values() if e["valid_observed_forward_snapshot"]]
        result[gate] = {"horizon": horizon, "completed_valid_snapshots": len(valid), "required_snapshots": SPEC["minimum_snapshots_per_gate"],
            "status": "INCONCLUSIVE", "reason": "INSUFFICIENT_MATURE_SNAPSHOTS" if len(valid) < 20 else "CONTROL_CENTER_MULTIDIMENSION_ADJUDICATION_REQUIRED",
            "rank_ic_series": [e["rank_ic"] for e in valid], "spread_series": [e["spreads"] for e in valid],
            "evidence_dimensions": SPEC["gate_dimensions"], "automatic_production_approval": False}
    return result


def checkpoint(root, expected, *, generated_at=None):
    validation = verify(root, expected)
    snapshots = [e["payload"] for e in replay_chain(root, KINDS[0])]
    evaluations = [e["payload"] for e in replay_chain(root, KINDS[2]) if e["payload"].get("kind") != "SOURCE_INTEGRITY_FAILURE"]
    at = generated_at or instant()
    gate_results = gates(evaluations)
    integrity_failures = [e["payload"] for e in replay_chain(root, KINDS[2]) if e["payload"].get("kind") == "SOURCE_INTEGRITY_FAILURE"]
    if integrity_failures:
        for gate in gate_results.values():
            gate.update(status="FAIL", reason="SOURCE_INTEGRITY_FAILURE_NOT_A_STATISTICAL_RESULT")
    schedules = []
    for s in snapshots:
        horizons = []
        for h in SPEC["horizons"]:
            latest = next(e["payload"] for e in reversed(replay_chain(root, KINDS[1])) if e["payload"]["shadow_snapshot_id"] == s["shadow_snapshot_id"] and e["payload"]["horizon"] == h)
            horizons.append({"trading_days": h, "status": "PENDING" if any(r["status"] == "PENDING" for r in latest["returns"]) else "FINALIZED",
                "by_market": {m: {"entry_dates": sorted({r["entry_price_date"] for r in latest["returns"] if r["market"] == m and r["entry_price_date"]}),
                    "maturity_dates": sorted({r["exit_price_date"] for r in latest["returns"] if r["market"] == m and r["exit_price_date"]})} for m in ("TWSE", "TPEX")},
                "rule": "FIRST_POST_SEAL_VERIFIED_MARKET_ENTRY_SESSION_PLUS_HORIZON"})
        schedules.append({"shadow_snapshot_id": s["shadow_snapshot_id"], "horizons": horizons})
    return {"artifact_kind": "SHADOW_FORWARD_CHECKPOINT_V1", "heads": expected, "verification": validation,
        "gates": gate_results, "source_integrity_failures": integrity_failures, "snapshot_count": len(snapshots), "generated_at": at,
        "next_evaluation_at": (_time(at) + timedelta(days=1)).isoformat(),
        "next_evaluation_role": "ADMINISTRATIVE_PRICE_EVIDENCE_RECHECK_NOT_ASSUMED_TRADING_SESSION_NO_SCHEDULE_CREATED",
        "maturity_schedule": schedules,
        "stability": [stability(a, b) for a, b in zip(snapshots, snapshots[1:])], "decision_eligible": False, "production_eligible": False}


def update(root, expected, snapshot_id, price_pin, *, as_of):
    from .provider_shadow_forward_prices import load_prices
    with exclusive_scan(Path(root)):
        verify(root, expected)
        snapshot = next((e["payload"] for e in replay_chain(root, KINDS[0]) if e["payload"]["shadow_snapshot_id"] == snapshot_id), None)
        require(snapshot is not None, "FORWARD_SNAPSHOT_UNKNOWN")
        require(_time(snapshot["sealed_at"]) <= _time(as_of) <= _time(instant()), "FORWARD_UPDATE_TIME_INVALID")
        require(not any(e["payload"].get("kind") == "SOURCE_INTEGRITY_FAILURE" for e in replay_chain(root, KINDS[2])), "FORWARD_PERSISTED_SOURCE_STOP")
        try:
            book = load_prices(price_pin, as_of=as_of, available_at=snapshot["forward_available_at"])
        except Exception as error:
            append_event(root, KINDS[2], {"kind": "SOURCE_INTEGRITY_FAILURE", "status": "FAIL_CLOSED", "shadow_snapshot_id": snapshot_id,
                "price_pin": price_pin, "error_type": type(error).__name__, "reason": str(error), "no_entry_overwritten": True})
            raise
        history = [e["payload"] for e in replay_chain(root, KINDS[1]) if e["payload"]["shadow_snapshot_id"] == snapshot_id]
        frozen = {}
        for state in history:
            for row in state["returns"]:
                if row["entry_price"] is not None:
                    frozen[(row["symbol"], row["entry_price_date"])] = {"close": row["entry_price"], "reference": row["entry_price_reference"]}
                for price in row["price_path"]:
                    frozen[(row["symbol"], price["date"])] = {"close": price["close"], "reference": price["reference"]}
        for key, price in frozen.items():
            if key in book["prices"]:
                require(book["prices"][key]["close"] == price["close"], "FORWARD_SAVED_PRICE_REVISION_REJECTED")
            book["prices"][key] = price
        for horizon in SPEC["horizons"]:
            prior = next(state for state in reversed(history) if state["horizon"] == horizon)
            resolved = resolve_returns(snapshot, horizon, book, as_of=as_of, prior_rows=prior["returns"])
            for row in resolved["returns"]:
                if row["entry_price"] is not None:
                    key = (row["symbol"], row["entry_price_date"])
                    if key in frozen:
                        row["entry_price_reference"] = frozen[key]["reference"]
                    else:
                        frozen[key] = {"close": row["entry_price"], "reference": row["entry_price_reference"]}
            if resolved["returns"] != prior["returns"]:
                append_event(root, KINDS[1], resolved)
            assessment = evaluate(snapshot, resolved)
            old_evaluations = [e["payload"] for e in replay_chain(root, KINDS[2]) if (e["payload"].get("shadow_snapshot_id"), e["payload"].get("horizon")) == (snapshot_id, horizon)]
            if not old_evaluations or old_evaluations[-1] != assessment:
                append_event(root, KINDS[2], assessment)
        return checkpoint(root, heads(root))
