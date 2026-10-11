"""Read-only, fail-safe CER078 observation; never intercept assertions or results."""
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import inspect
import json
import locale
import os
from pathlib import Path
import platform
import sys
import time
import traceback

SAFE_ENVIRONMENT = ("PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "PYTHONHASHSEED", "TEMP", "TMP", "TZ", "LANG", "LC_ALL")
TERMINAL_SUBGATES = (
    "previous_state_binding", "full_lineage", "evening_incremental_evidence_boundary",
    "protected_baseline_integrity", "protected_field_violation_count_zero", "coverage_30",
    "determinism", "production_state_idempotency", "roy", "ai", "ledger", "ranking",
    "learning", "watch", "model_freeze", "failure_closed_behavior",
)


def environment():
    versions = {}
    for name in ("lxml", "tzdata", "PyYAML", "numpy", "pandas"):
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = None
    return {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "timezone": list(time.tzname), "locale": locale.setlocale(locale.LC_ALL, None),
        "filesystem_encoding": sys.getfilesystemencoding(), "preferred_encoding": locale.getpreferredencoding(False),
        "cwd": os.getcwd(), "dependencies": versions,
        "selected_nonsecret_environment": {key: os.environ.get(key) for key in SAFE_ENVIRONMENT}}


def test_ids(suite):
    import unittest
    if isinstance(suite, unittest.TestSuite): return [i for item in suite for i in test_ids(item)]
    return [suite.id()]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def summaries(value, prefix, gates, identities):
    if isinstance(value, dict):
        for key, item in value.items():
            locator = prefix + "/" + str(key)
            if isinstance(item, (dict, list)):
                summaries(item, locator, gates, identities)
            elif key.endswith(("_id", "_hash", "_sha256")) and isinstance(item, str):
                identities[locator] = item
            elif item in ("PASS", "FAIL", "NOT_RUN") or isinstance(item, bool) or key.endswith("_count"):
                gates[locator] = item
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)):
                summaries(item, prefix + "/" + str(index), gates, identities)


class Observer:
    def __init__(self, owner, *, context=None, event_path=None):
        self.owner = owner
        self.events = []
        self.diagnostic_errors = []
        self.test_id = None
        self.tool = 4
        self.context = context or {}
        self.event_path = Path(event_path) if event_path else None
        self.stream = None

    def record(self, value):
        self.events.append(value)
        if self.stream:
            self.stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
            self.stream.flush()
            os.fsync(self.stream.fileno())

    def diagnostic_error(self, error):
        # Telemetry must never replace the original exception or change its verdict.
        self.diagnostic_errors.append({"timestamp": utc_now(), "error_type": type(error).__name__,
                                       "message": str(error)})

    def terminal(self, frame):
        local = frame.f_locals
        vector = list(local["terminal"])
        if len(vector) != len(TERMINAL_SUBGATES):
            raise ValueError("DIAGNOSTIC_TERMINAL_VECTOR_SCHEMA_CHANGED")
        gates, identities, hashes = {}, {}, {}
        for name in ("artifacts", "source_bundle", "previous_1200", "state_1200", "snapshot",
                     "dry_a", "dry_b", "delta", "failure", "freeze", "first", "replay"):
            value = local.get(name)
            summaries(value, name, gates, identities)
            hashes[name] = digest(value)
        state_path = Path(local["state_root"]).resolve()
        paths = (state_path, Path("artifacts/test-cer078-partial-failure-state").resolve())
        file_hashes = {}
        for root in paths:
            if root.exists():
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        file_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"terminal_subgate_vector": dict(zip(TERMINAL_SUBGATES, vector)),
                "terminal_vector_raw": vector, "all_gate_values": gates,
                "state_source_bundle_identities": identities,
                "relevant_artifact_content_hashes": hashes, "relevant_artifact_file_hashes": file_hashes,
                "paths": {"state_root": str(state_path), "partial_failure_root": str(paths[1]),
                          "temp": os.environ.get("TEMP"), "tmp": os.environ.get("TMP")},
                "owner_sha256": hashlib.sha256(Path(self.owner.__file__).read_bytes()).hexdigest()}

    def raised(self, code, offset, exception):
        if code.co_filename != self.owner.__file__: return
        try:
            event = {"test_id": self.test_id, "file": code.co_filename, "function": code.co_name,
                "offset": offset, "exception": type(exception).__name__, "message": str(exception),
                "traceback": "".join(traceback.format_exception(exception)), "timestamp": utc_now()}
            if code.co_name == "build_cer078_artifacts" and str(exception) == "CER078_TERMINAL_GATE_FAIL":
                frame = inspect.currentframe()
                try:
                    while frame is not None and frame.f_code is not code:
                        frame = frame.f_back
                    if frame is None: raise ValueError("DIAGNOSTIC_OWNER_FRAME_UNAVAILABLE")
                    event.update(self.terminal(frame), context=self.context)
                finally:
                    del frame
            self.record(event)
        except Exception as error:
            self.diagnostic_error(error)

    def returned(self, code, offset, value):
        try:
            if code.co_name == "failure_gate_results":
                self.record({"test_id": self.test_id, "function": code.co_name, "result": value,
                             "timestamp": utc_now()})
        except Exception as error:
            self.diagnostic_error(error)

    def __enter__(self):
        if self.event_path:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)
            self.stream = self.event_path.open("x", encoding="utf-8")
        try:
            sys.monitoring.use_tool_id(self.tool, "cer078-read-only-diagnostics")
            sys.monitoring.register_callback(self.tool, sys.monitoring.events.RAISE, self.raised)
            sys.monitoring.register_callback(self.tool, sys.monitoring.events.PY_RETURN, self.returned)
            sys.monitoring.set_events(self.tool, sys.monitoring.events.RAISE)
            sys.monitoring.set_local_events(self.tool, self.owner.failure_gate_results.__code__, sys.monitoring.events.PY_RETURN)
        except Exception:
            if self.stream: self.stream.close()
            raise
        return self

    def __exit__(self, *exc):
        try: sys.monitoring.free_tool_id(self.tool)
        except Exception as error: self.diagnostic_error(error)
        if self.stream:
            try: self.stream.close()
            except Exception as error: self.diagnostic_error(error)
