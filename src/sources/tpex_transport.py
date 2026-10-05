"""Bounded complete-response transport for approved TPEx JSON requests."""
import hashlib
import json
import time
from datetime import datetime, timezone
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError

MAX_ATTEMPTS = 3
ATTEMPT_TIMEOUT = 30
TOTAL_BUDGET = 95


class TPExJSONTransportError(RuntimeError):
    def __init__(self, reason, diagnostics):
        super().__init__(reason)
        self.diagnostics = diagnostics


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("records", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
        tables = payload.get("tables")
        if isinstance(tables, list) and tables and isinstance(tables[0], dict):
            return tables[0].get("data")
    return None


def fetch_official_json(request, *, opener, attempts=MAX_ATTEMPTS,
                        blocking_reason="TPEX_OFFICIAL_JSON_RETRIEVAL_FAILED"):
    if not 1 <= attempts <= MAX_ATTEMPTS:
        raise ValueError("TPEX_RETRY_LIMIT_INVALID")
    deadline = time.monotonic() + TOTAL_BUDGET
    history = []
    for number in range(1, attempts + 1):
        attempt_deadline = min(deadline, time.monotonic() + ATTEMPT_TIMEOUT)
        item = {"attempt": number, "started_at": _now(), "completed_at": None,
                "http_status": None, "content_type": None,
                "response_bytes": 0, "content_length_header": None,
                "exception_type": None, "parse_status": "NOT_RUN",
                "retry_reason": None, "backoff_seconds": 0}
        body = bytearray()
        retryable = False
        try:
            remaining = attempt_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("TPEX_TOTAL_BUDGET_EXHAUSTED")
            with opener(request, timeout=remaining) as response:
                item["http_status"] = getattr(response, "status", None)
                if item["http_status"] is None:
                    item["http_status"] = response.getcode()
                item["content_type"] = response.headers.get("Content-Type", "")
                item["content_length_header"] = response.headers.get("Content-Length")
                item["http_date"] = response.headers.get("Date")
                item["final_url"] = response.geturl() if hasattr(response, "geturl") else request.full_url
                if item["final_url"] != request.full_url:
                    raise ValueError("TPEX_UNAPPROVED_REDIRECT")
                if item["http_status"] != 200:
                    raise HTTPError(request.full_url, item["http_status"], "HTTP failure", response.headers, None)
                # read1 lets the wall-clock budget bound slow/trickling bodies.
                if hasattr(response, "read1"):
                    while True:
                        remaining = attempt_deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("TPEX_ATTEMPT_BUDGET_EXHAUSTED")
                        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                        if sock is not None:
                            sock.settimeout(remaining)
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        body.extend(chunk)
                else:
                    body.extend(response.read())
            item["response_bytes"] = len(body)
            item["first_safe_body_characters"] = body[:120].decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
            if time.monotonic() > attempt_deadline:
                raise TimeoutError("TPEX_ATTEMPT_BUDGET_EXHAUSTED")
            length = item["content_length_header"]
            if length is not None and int(length) != len(body):
                raise IncompleteRead(bytes(body), max(0, int(length) - len(body)))
            if not body:
                raise IncompleteRead(b"", 1)
            payload = json.loads(body.decode("utf-8-sig"))
            item["parse_status"] = "PASS"
            rows = records(payload)
            if isinstance(rows, list) and not rows:
                raise IncompleteRead(bytes(body), 1)
            if not isinstance(rows, list) or not rows or any(not isinstance(row, (dict, list)) for row in rows):
                raise ValueError("TPEX_JSON_STRUCTURAL_VALIDATION_FAILED")
            if time.monotonic() > deadline:
                raise TimeoutError("TPEX_TOTAL_BUDGET_EXHAUSTED")
            item["body_sha256"] = hashlib.sha256(body).hexdigest()
            item["completed_at"] = _now()
            history.append(item)
            return {"payload": payload, "body_sha256": item["body_sha256"],
                    "diagnostics": {**item, "attempt_count": number,
                        "final_attempt": number, "attempts": history,
                        "record_count": len(rows), "fallback_used": False,
                        "official_endpoint": request.full_url}}
        except HTTPError as exc:
            item["http_status"] = exc.code
            if exc.headers:
                item["content_type"] = exc.headers.get("Content-Type", "")
                item["content_length_header"] = exc.headers.get("Content-Length")
            retryable = exc.code in (408, 429) or 500 <= exc.code < 600
            item["exception_type"] = type(exc).__name__
            item["retry_reason"] = f"HTTP_{exc.code}"
        except (IncompleteRead, ConnectionError, TimeoutError, URLError, OSError,
                json.JSONDecodeError, UnicodeDecodeError) as exc:
            partial = getattr(exc, "partial", b"")
            item["response_bytes"] = len(body) + (len(partial) if isinstance(partial, bytes) and partial != bytes(body) else 0)
            item["exception_type"] = type(exc).__name__
            item["retry_reason"] = type(exc).__name__
            retryable = True
        except ValueError as exc:
            item["exception_type"] = type(exc).__name__
            item["retry_reason"] = str(exc)
        item["completed_at"] = _now()
        if item["parse_status"] != "PASS":
            item["parse_status"] = "FAIL"
        history.append(item)
        delay = 2 ** (number - 1)
        if not retryable or number == attempts or time.monotonic() + delay >= deadline:
            break
        item["backoff_seconds"] = delay
        time.sleep(delay)
    diagnostics = {**history[-1], "attempts": history,
                   "attempt_count": len(history), "final_blocking_reason": blocking_reason,
                   "fallback_used": False}
    raise TPExJSONTransportError(blocking_reason + ":" + str(history[-1]["exception_type"]), diagnostics)
