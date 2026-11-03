"""Synthetic semantic review for the activation acquisition CLI candidate.

The review executes the in-memory acquisition CLI with a synthetic API key and a
fake provider runtime. It proves output custody, evidence hashing, zero-secret
persistence, and authoritative Phase2 admission compatibility without real network
or credential access.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from typing import Any, Mapping
from unittest.mock import patch

from .intraday_activation_candidate_syntax_review import (
    validate_activation_candidate_syntax,
)
from .intraday_phase2_admission import qualify_phase2_intraday_feed


class AcquisitionSemanticReviewError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AcquisitionSemanticReviewError(reason)


@contextmanager
def _cwd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class _FakeRuntime:
    def __init__(self, *, now_utc: datetime, fail: str | None = None):
        self.now_utc = now_utc
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def acquire_intraday_feed(
        self,
        symbols,
        *,
        trading_date: str,
        cadence: str,
        api_key: str,
    ):
        self.calls.append({
            "symbols": list(symbols),
            "trading_date": trading_date,
            "cadence": cadence,
            "api_key_present": bool(api_key),
            "api_key": api_key,
        })
        if self.fail:
            raise RuntimeError(self.fail)
        records = []
        raw = []
        for symbol, market in symbols:
            payload = {
                "symbol": symbol,
                "lastUpdated": self.now_utc.isoformat(),
                "lastPrice": 100.0,
                "total": {"tradeVolume": 1000, "tradeValue": 100000.0},
            }
            records.append({
                "symbol": symbol,
                "market": market,
                "timestamp": self.now_utc.isoformat(),
                "price": 100.0,
                "volume": 1000.0,
                "turnover": 100000.0,
            })
            raw.append({"symbol": symbol, "market": market, "payload": payload})
        return {
            "records": records,
            "raw_evidence": raw,
            "requests": len(records),
            "automatic_retries": 0,
            "fallback_used": False,
        }


def _load_cli(source: str, runtime: _FakeRuntime) -> dict[str, Any]:
    module = types.ModuleType("src.intraday_provider_runtime")
    module.acquire_intraday_feed = runtime.acquire_intraday_feed
    namespace: dict[str, Any] = {
        "__name__": "rate_candidate_acquisition_synthetic",
        "__file__": "<in-memory-acquisition-candidate>",
    }
    with patch.dict(sys.modules, {"src.intraday_provider_runtime": module}):
        exec(
            compile(source, "<in-memory-acquisition-candidate>", "exec"),
            namespace,
            namespace,
        )
    return namespace


def _args(*, cadence: str, output: str, raw_output: str) -> list[str]:
    return [
        "acquire_intraday_provider_feed.py",
        "--trading-date", "2026-11-04",
        "--cadence", cadence,
        "--previous-state-id", "rate-state-previous",
        "--previous-state-hash", "a" * 64,
        "--output", output,
        "--raw-evidence-output", raw_output,
    ]


def _expected_paths(cadence: str) -> tuple[str, str]:
    compact = cadence.replace(":", "")
    return (
        f"artifacts/production_{compact}/RATE_AUTHORIZED_INTRADAY_FEED.json",
        f"artifacts/production_{compact}/RATE_AUTHORIZED_INTRADAY_RAW_EVIDENCE.json",
    )


def _run_main(
    namespace: Mapping[str, Any],
    runtime: _FakeRuntime,
    *,
    root: Path,
    cadence: str,
    output: str,
    raw_output: str,
    secret_name: str,
    api_key: str | None,
):
    env = {} if api_key is None else {secret_name: api_key}
    with _cwd(root), patch.object(sys, "argv", _args(
        cadence=cadence, output=output, raw_output=raw_output
    )), patch.dict(os.environ, env, clear=True):
        return namespace["main"]()


def review_candidate_acquisition_synthetic(
    candidate_files: Mapping[str, str],
    *,
    expected_acquisition_sha256: str,
    expected_provider_name: str,
    expected_secret_name: str,
    trading_date: str,
    cadence: str,
    now_utc: datetime,
) -> dict[str, Any]:
    require(now_utc.tzinfo is not None and now_utc.utcoffset() is not None,
            "ACQUISITION_SEMANTIC_NOW_TIMEZONE_REQUIRED")
    require(cadence in {"09:30", "12:00"}, "ACQUISITION_SEMANTIC_CADENCE_INVALID")
    require(trading_date == "2026-11-04", "ACQUISITION_SEMANTIC_TRADING_DATE_INVALID")
    validate_activation_candidate_syntax(
        candidate_files,
        expected_provider_name=expected_provider_name,
        expected_secret_name=expected_secret_name,
    )
    source = candidate_files["scripts/acquire_intraday_provider_feed.py"]
    actual_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    require(actual_hash == expected_acquisition_sha256,
            "ACQUISITION_SEMANTIC_SOURCE_HASH_MISMATCH")

    synthetic_key = "synthetic-key-not-a-real-secret"
    output, raw_output = _expected_paths(cadence)

    # Success path.
    success_runtime = _FakeRuntime(now_utc=now_utc)
    success_ns = _load_cli(source, success_runtime)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = _run_main(
            success_ns,
            success_runtime,
            root=root,
            cadence=cadence,
            output=output,
            raw_output=raw_output,
            secret_name=expected_secret_name,
            api_key=synthetic_key,
        )
        require(result == 0, "ACQUISITION_SEMANTIC_MAIN_RESULT_INVALID")
        require(len(success_runtime.calls) == 1,
                "ACQUISITION_SEMANTIC_RUNTIME_CALL_COUNT_INVALID")
        call = success_runtime.calls[0]
        require(call["api_key"] == synthetic_key
                and call["cadence"] == cadence
                and call["trading_date"] == trading_date
                and len(call["symbols"]) == 30,
                "ACQUISITION_SEMANTIC_RUNTIME_BINDING_INVALID")
        feed_path = root / output
        raw_path = root / raw_output
        require(feed_path.is_file() and raw_path.is_file(),
                "ACQUISITION_SEMANTIC_OUTPUT_MISSING")
        feed_bytes = feed_path.read_bytes()
        raw_bytes = raw_path.read_bytes()
        require(synthetic_key.encode() not in feed_bytes
                and synthetic_key.encode() not in raw_bytes,
                "ACQUISITION_SEMANTIC_SECRET_PERSISTED")
        feed = json.loads(feed_bytes)
        require(feed.get("payload_references") == [{
            "path": raw_output,
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        }], "ACQUISITION_SEMANTIC_RAW_REFERENCE_INVALID")
        qualified = qualify_phase2_intraday_feed(
            feed,
            trading_date=trading_date,
            cadence=cadence,
            now_utc=now_utc,
        )
        require(qualified.get("validation_status") == "PASS"
                and qualified.get("coverage") == "30/30"
                and qualified.get("market_counts") == {"TWSE": 25, "TPEX": 5},
                "ACQUISITION_SEMANTIC_PHASE2_ADMISSION_FAILED")
        success_evidence = {
            "feed_sha256": hashlib.sha256(feed_bytes).hexdigest(),
            "raw_evidence_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "coverage": qualified["coverage"],
            "market_counts": qualified["market_counts"],
        }

    # Missing key must fail before provider runtime and before any output.
    missing_runtime = _FakeRuntime(now_utc=now_utc)
    missing_ns = _load_cli(source, missing_runtime)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            _run_main(
                missing_ns, missing_runtime, root=root, cadence=cadence,
                output=output, raw_output=raw_output,
                secret_name=expected_secret_name, api_key=None,
            )
        except RuntimeError as exc:
            require("API_KEY_MISSING" in str(exc),
                    "ACQUISITION_SEMANTIC_MISSING_KEY_REASON_INVALID")
        else:
            raise AcquisitionSemanticReviewError(
                "ACQUISITION_SEMANTIC_MISSING_KEY_FAIL_CLOSED_MISSING"
            )
        require(len(missing_runtime.calls) == 0,
                "ACQUISITION_SEMANTIC_MISSING_KEY_RUNTIME_CALL")
        require(not any(root.rglob("*")),
                "ACQUISITION_SEMANTIC_MISSING_KEY_OUTPUT_CREATED")

    # Invalid output arguments must fail before getenv/runtime.
    bad_cases = (
        ("../escape.json", raw_output, "OUTPUT_PATH_FORBIDDEN"),
        ("artifacts/production_1200/RATE_AUTHORIZED_INTRADAY_FEED.json"
         if cadence == "09:30"
         else "artifacts/production_0930/RATE_AUTHORIZED_INTRADAY_FEED.json",
         raw_output, "OUTPUT_PATH_FORBIDDEN"),
        (output, "../raw.json", "RAW_EVIDENCE_PATH_FORBIDDEN"),
    )
    for bad_output, bad_raw, reason in bad_cases:
        runtime = _FakeRuntime(now_utc=now_utc)
        namespace = _load_cli(source, runtime)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with _cwd(root), patch.object(sys, "argv", _args(
                cadence=cadence, output=bad_output, raw_output=bad_raw
            )), patch.object(os, "getenv",
                side_effect=AssertionError("SECRET_READ_TOO_EARLY")):
                try:
                    namespace["main"]()
                except RuntimeError as exc:
                    require(reason in str(exc),
                            "ACQUISITION_SEMANTIC_BAD_PATH_REASON_INVALID")
                else:
                    raise AcquisitionSemanticReviewError(
                        "ACQUISITION_SEMANTIC_BAD_PATH_FAIL_CLOSED_MISSING"
                    )
            require(len(runtime.calls) == 0,
                    "ACQUISITION_SEMANTIC_BAD_PATH_RUNTIME_CALL")
            require(not any(root.rglob("*")),
                    "ACQUISITION_SEMANTIC_BAD_PATH_OUTPUT_CREATED")

    # Existing output must be preserved and fail before secret access/runtime.
    for existing in (output, raw_output):
        runtime = _FakeRuntime(now_utc=now_utc)
        namespace = _load_cli(source, runtime)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / existing
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"protected")
            with _cwd(root), patch.object(sys, "argv", _args(
                cadence=cadence, output=output, raw_output=raw_output
            )), patch.object(os, "getenv",
                side_effect=AssertionError("SECRET_READ_TOO_EARLY")):
                try:
                    namespace["main"]()
                except RuntimeError as exc:
                    require("OUTPUT_EXISTS" in str(exc),
                            "ACQUISITION_SEMANTIC_EXISTING_OUTPUT_REASON_INVALID")
                else:
                    raise AcquisitionSemanticReviewError(
                        "ACQUISITION_SEMANTIC_EXISTING_OUTPUT_FAIL_CLOSED_MISSING"
                    )
            require(target.read_bytes() == b"protected",
                    "ACQUISITION_SEMANTIC_EXISTING_OUTPUT_MODIFIED")
            require(len(runtime.calls) == 0,
                    "ACQUISITION_SEMANTIC_EXISTING_OUTPUT_RUNTIME_CALL")

    # Provider runtime failure occurs before output creation.
    failing_runtime = _FakeRuntime(now_utc=now_utc, fail="SYNTHETIC_RUNTIME_FAIL")
    failing_ns = _load_cli(source, failing_runtime)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            _run_main(
                failing_ns, failing_runtime, root=root, cadence=cadence,
                output=output, raw_output=raw_output,
                secret_name=expected_secret_name, api_key=synthetic_key,
            )
        except RuntimeError as exc:
            require("SYNTHETIC_RUNTIME_FAIL" in str(exc),
                    "ACQUISITION_SEMANTIC_RUNTIME_FAILURE_REASON_INVALID")
        else:
            raise AcquisitionSemanticReviewError(
                "ACQUISITION_SEMANTIC_RUNTIME_FAILURE_NOT_PROPAGATED"
            )
        require(len(failing_runtime.calls) == 1,
                "ACQUISITION_SEMANTIC_RUNTIME_FAILURE_CALL_COUNT_INVALID")
        require(not any(path.is_file() for path in root.rglob("*")),
                "ACQUISITION_SEMANTIC_RUNTIME_FAILURE_OUTPUT_CREATED")

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_ACQUISITION_SEMANTIC_REVIEW_V1",
        "validation_status": "PASS",
        "transport": "SYNTHETIC_FAKE_RUNTIME_ONLY",
        "real_provider_requests": 0,
        "synthetic_runtime_calls_success": 1,
        "output_path": output,
        "raw_evidence_output_path": raw_output,
        "output_custody": "FIXED_CADENCE_PATH_EXCLUSIVE_CREATE",
        "secret_persisted": False,
        "phase2_admission_coverage": success_evidence["coverage"],
        "market_counts": success_evidence["market_counts"],
        "feed_sha256": success_evidence["feed_sha256"],
        "raw_evidence_sha256": success_evidence["raw_evidence_sha256"],
        "missing_key_runtime_calls": 0,
        "bad_path_runtime_calls": 0,
        "existing_output_runtime_calls": 0,
        "provider_accepted": False,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "repository_writes": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }
