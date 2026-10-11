"""Read-only CER078 observation; no SUT replacement or assertion interception."""
import importlib.metadata
import locale
import os
import platform
import sys
import time
import traceback

SAFE_ENVIRONMENT = ("PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "PYTHONHASHSEED", "TEMP", "TMP", "TZ", "LANG", "LC_ALL")


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


class Observer:
    def __init__(self, owner):
        self.owner = owner
        self.events = []
        self.test_id = None
        self.tool = 4

    def raised(self, code, offset, exception):
        if code.co_filename != self.owner.__file__: return
        self.events.append({"test_id": self.test_id, "file": code.co_filename, "function": code.co_name,
            "offset": offset, "exception": type(exception).__name__, "message": str(exception),
            "traceback": "".join(traceback.format_exception(exception))})

    def returned(self, code, offset, value):
        if code.co_name == "failure_gate_results":
            self.events.append({"test_id": self.test_id, "function": code.co_name, "result": value})

    def __enter__(self):
        sys.monitoring.use_tool_id(self.tool, "cer078-read-only-diagnostics")
        sys.monitoring.register_callback(self.tool, sys.monitoring.events.RAISE, self.raised)
        sys.monitoring.register_callback(self.tool, sys.monitoring.events.PY_RETURN, self.returned)
        sys.monitoring.set_events(self.tool, sys.monitoring.events.RAISE)
        sys.monitoring.set_local_events(self.tool, self.owner.failure_gate_results.__code__, sys.monitoring.events.PY_RETURN)
        return self

    def __exit__(self, *exc): sys.monitoring.free_tool_id(self.tool)
