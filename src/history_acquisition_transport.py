"""Exactly one approved historical GET/POST; no retry, proxy, redirect or fallback."""
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

from .eps_duration_facts.model import require
from .session_discovery_transport import NoRedirect


def dispatch_once(entry):
    from .history_acquisition_execution import request_entry
    expected = request_entry({key: entry[key] for key in ("market", "product", "symbol", "period")}, entry["ordinal"])
    require(entry == expected, "HISTORY_TRANSPORT_BINDING_MISMATCH")
    body = urlencode(entry["parameters"]).encode("utf-8") if entry["method"] == "POST" else None
    headers = {"Accept": "application/json", "User-Agent": "RATE-History-Evidence/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(entry["request_url"], data=body, headers=headers, method=entry["method"])
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        return {"raw_bytes": response.read(), "http_status": response.code, "final_url": response.geturl(),
                "content_type": response.headers.get("Content-Type", ""), "location": response.headers.get("Location")}
