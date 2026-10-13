"""One public HTTPS attempt; no credentials, redirect, retry or alternate route."""
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def dispatch_once(entry):
    # Explicitly disable environment proxy discovery and use default TLS verification.
    from .session_discovery_execution import targets
    if entry not in targets():
        raise ValueError("DISCOVERY_TRANSPORT_TARGET_MISMATCH")
    request = Request(entry["endpoint"], method="GET", headers={
        "Accept": "application/json", "User-Agent": "RATE-Session-Discovery/1.0"})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        return {"raw_bytes": response.read(), "http_status": response.code,
                "final_url": response.geturl(),
                "content_type": response.headers.get("Content-Type", ""),
                "location": response.headers.get("Location")}
