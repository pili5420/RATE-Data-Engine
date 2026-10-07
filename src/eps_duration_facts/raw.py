"""Portable replay resolves bodies by hash without rewriting archived receipts."""
import hashlib
from datetime import datetime
from urllib.parse import urlsplit

from .model import Rejected, require


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def completed_attempt(receipt):
    require(receipt.get("fallback_used") is False, "FALLBACK_FORBIDDEN")
    attempts = receipt.get("attempts", [])
    successful = [a for a in attempts if a.get("transport_integrity") == "PASS"]
    require(len(successful) == 1 and successful[0] == attempts[-1],
            "COMPLETED_RESPONSE_UNPROVEN")
    return successful[0]


def verify_receipt(receipt, data, expected_endpoint):
    attempt = completed_attempt(receipt)
    require(receipt.get("endpoint") == expected_endpoint, "WRONG_ENDPOINT")
    require(urlsplit(expected_endpoint).scheme == "https", "SOURCE_NOT_HTTPS")
    require(attempt.get("final_url") == expected_endpoint, "UNAPPROVED_REDIRECT")
    require(attempt.get("http_status") == 200, "HTTP_NOT_200")
    require(data and len(data) == attempt.get("response_bytes"), "BODY_LENGTH_MISMATCH")
    length = attempt.get("content_length")
    require(length in (None, "") or int(length) == len(data), "CONTENT_LENGTH_MISMATCH")
    require(sha256(data) == attempt.get("body_sha256"), "BODY_HASH_MISMATCH")
    require(datetime.fromisoformat(attempt["retrieved_at"]).tzinfo is not None,
            "OBSERVATION_TIMEZONE_UNPROVEN")
    return attempt


def audit_archive(archive, prefix):
    """Count receipts, attempts, unique bodies and filing identities separately."""
    import json
    receipts = {}
    bodies = {}
    completed = failed = failed_attempts = 0
    filings = {}
    source_binding_rejections = {}
    observations = {}
    for name in sorted(archive.namelist()):
        if not name.startswith(prefix + "/receipts/") or not name.endswith(".json"):
            continue
        receipt = json.loads(archive.read(name))
        receipts[name] = sha256(archive.read(name))
        failed_attempts += sum(a.get("transport_integrity") != "PASS"
                               for a in receipt.get("attempts", []))
        if not any(a.get("transport_integrity") == "PASS"
                   for a in receipt.get("attempts", [])):
            failed += 1
            require(not receipt.get("body_sha256"), "FAILED_BODY_AS_RECEIPT")
            continue
        attempt = completed_attempt(receipt)
        digest = attempt["body_sha256"]
        data = archive.read(prefix + "/raw/" + digest + ".bin")
        require(len(data) == attempt["response_bytes"] and sha256(data) == digest,
                "ARCHIVE_BODY_TAMPERED")
        try:
            verify_receipt(receipt, data, receipt["endpoint"])
        except Rejected as exc:
            source_binding_rejections[name] = str(exc)
        completed += 1
        bodies.setdefault(digest, []).append(name)
        observations.setdefault(digest, []).append(attempt["retrieved_at"])
        label = receipt["label"]
        if label.endswith(("-download", "-preview")) and label[:4] in ("2330", "6488"):
            key = label.rsplit("-", 1)[0]
            filings.setdefault(key, []).append(name)
    return {"receipt_count": len(receipts), "completed_responses": completed,
            "failed_responses": failed, "failed_attempts": failed_attempts,
            "unique_body_count": len(bodies), "filing_identity_count": len(filings),
            "filing_responses": sum(map(len, filings.values())),
            "same_body_multiple_receipts": {k: v for k, v in bodies.items() if len(v) > 1},
            "receipt_sha256": receipts, "body_to_receipts": bodies,
            "filing_to_receipts": filings, "source_binding_rejections": source_binding_rejections,
            "first_verified_observed_at": {h: min(times) for h, times in observations.items()}}
