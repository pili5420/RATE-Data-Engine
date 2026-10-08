"""Versioned capture-boundary timing; no network implementation or retries."""
from contextlib import contextmanager
import os
from pathlib import Path
import time
from uuid import uuid4

from .eps_duration_facts.model import require

PROTOCOL = "FINMIND_CAPTURE_BOUNDARY_MONOTONIC_V1"


class DispatchGate:
    def __init__(self, interval, *, prior_dispatch=False, clock=time.monotonic, sleep=time.sleep, utc):
        require(interval >= 13, "UNSAFE_DISPATCH_INTERVAL")
        self.interval, self.clock, self.sleep, self.utc = interval, clock, sleep, utc
        self.session_id = str(uuid4())
        self.clock_domain = "PROCESS_SESSION:" + self.session_id
        self.last = None
        self.wait_anchor = None
        self.origin = clock()
        self.prior_dispatch = prior_dispatch

    def delay(self):
        current = self.clock()
        anchor = self.wait_anchor if self.wait_anchor is not None else self.origin if self.prior_dispatch else None
        if anchor is None:
            return 0
        require(current >= anchor, "MONOTONIC_CLOCK_REGRESSED")
        return max(0, self.interval - (current - anchor))

    def boundary(self, request_identity):
        started = self.clock()
        previous_anchor = self.wait_anchor if self.wait_anchor is not None else self.origin if self.prior_dispatch else None
        while self.delay() > 0:
            before = self.clock()
            self.sleep(self.delay())
            require(self.clock() > before, "MONOTONIC_WAIT_DID_NOT_ADVANCE")
        dispatched = self.clock()
        gap = None if self.last is None else dispatched - self.last
        require(gap is None or gap >= self.interval, "DISPATCH_INTERVAL_VIOLATION")
        value = {"protocol": PROTOCOL, "request_identity": request_identity,
            "session_identity": self.session_id, "clock_domain": self.clock_domain,
            "monotonic_timestamp": dispatched, "utc_timestamp": self.utc(),
            "previous_dispatch_interval_seconds": gap,
            "actual_wait_seconds": dispatched - started, "minimum_interval_seconds": self.interval,
            "previous_wait_anchor_monotonic": previous_anchor,
            "prior_session_continuity": "UNPROVEN_CONSERVATIVE_WAIT" if self.last is None and self.prior_dispatch else
                "NO_PRIOR_DISPATCH" if self.last is None else "SAME_MONOTONIC_DOMAIN",
            "measurement_boundary": "CAPTURE_CALL_NOT_HTTP_WIRE_START"}
        self.last = dispatched
        self.wait_anchor = dispatched
        return value

    def check_outbound(self, evidence):
        current = self.clock()
        require(current >= evidence["monotonic_timestamp"], "MONOTONIC_CLOCK_REGRESSED")
        anchor = evidence["previous_wait_anchor_monotonic"]
        require(anchor is None or current - anchor >= self.interval, "DISPATCH_INTERVAL_VIOLATION")

    def completed(self):
        self.wait_anchor = self.clock()


@contextmanager
def exclusive_scan(root):
    """OS-held lock survives stale files, but is released on process termination."""
    with (Path(root) / ".scan.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            lock = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            lock = lambda: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(stream, fcntl.LOCK_UN)
        try:
            lock()
        except OSError as exc:
            raise RuntimeError("COVERAGE_WRITER_ALREADY_ACTIVE") from exc
        try:
            yield
        finally:
            stream.seek(0)
            unlock()
