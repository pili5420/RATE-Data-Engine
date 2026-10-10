"""Offline qualification only. No acquisition, active owner or production binding."""
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs

from lxml import html as html_parser

from .eps_duration_facts.model import require
from .eps_duration_facts.pit import clock, select_eight, select_version, validate_pit
from .eps_duration_facts.validator import validate_fact_replay
from .sources.fundamental_history import (
    MOPS_EPS_ENDPOINT, _decode_response, _eps_official_no_data, discover_eps_identity,
)
from .sources.mops_raw_evidence import load_response

BOUNDARY = {"qualification_only": True, "production_eligible": False,
            "original_eight_quarter_coverage_credit": 0, "fallback_allowed": False,
            "formal_warmup_gate": "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN"}


def inspect_mops_response(root, reference, plan):
    """Replay the original receipt against its original owner, never today's hash."""
    receipt, body = load_response(root, reference, plan)
    require(receipt["domain"] == "eps" and receipt["endpoint"] == MOPS_EPS_ENDPOINT
            and receipt["final_url"] == MOPS_EPS_ENDPOINT and receipt["http_status"] == 200,
            "QUALIFICATION_SOURCE_BINDING_INVALID")
    require(receipt["request_method"] == "POST", "QUALIFICATION_REQUEST_BINDING_INVALID")
    year, quarter = receipt["requested_period"].split("Q")
    params = parse_qs(bytes.fromhex(receipt["request_body_hex"]).decode("ascii"), strict_parsing=True)
    require(params.get("year") == [str(int(year) - 1911)]
            and params.get("season") == [f"{int(quarter):02d}"]
            and params.get("TYPEK") == [{"TWSE": "sii", "TPEX": "otc"}[receipt["market"]]],
            "QUALIFICATION_REQUEST_BINDING_INVALID")
    clock(receipt["retrieval_timestamp"])
    length = receipt.get("content_length")
    require(length in (None, "") or int(length) == len(body), "QUALIFICATION_LENGTH_MISMATCH")
    root_node = html_parser.fromstring(_decode_response(body))
    for node in root_node.xpath("//script | //style"):
        node.drop_tree()
    tree = root_node.getroottree()
    headers = [{"locator": tree.getpath(n), "text": " ".join(n.itertext()).strip()}
               for n in root_node.xpath("//th")]
    # Owner identity is diagnostic only: it does not prove duration or public version.
    owner_identity = discover_eps_identity(_decode_response(body))
    return {**BOUNDARY, "MOPS_FORMAL_EPS_PERIOD_IDENTITY": "NOT_PROVEN",
            "receipt_reference": reference, "raw_sha256": receipt["body_sha256"],
            "raw_bytes": len(body), "market": receipt["market"],
            "requested_period_not_response_proof": receipt["requested_period"],
            "http_status": receipt["http_status"], "observed_at": receipt["retrieval_timestamp"],
            "original_owner_sha256": receipt["parser_sha256"], "owner_identity": owner_identity,
            "official_query_no_data": _eps_official_no_data(_decode_response(body)),
            "visible_text": " ".join(root_node.text_content().split()), "headers": headers,
            "company_identity": None, "exact_report_duration": None,
            "source_publication_time": None, "revision_identity": None,
            "historical_pit_status": "UNPROVEN",
            "limits": ["Summary query is not a filing-context/public-version proof",
                       "Request period, report generation date and retrieval time are not publication evidence",
                       "No-data does not prove nonpublication, issuer absence or permanent unavailability"]}


def qualify_eight(materials, index, cutoff):
    """Compose existing fact/receipt/PIT gates; never activate a formal EPS consumer.

    Index completeness/public-version attestations remain explicit evidence inputs.
    This function neither manufactures nor acquires those attestations.
    Each material is (fact, expectation, receipt, exact bytes, fiscal calendar).
    """
    anchor, window = select_eight(index, cutoff)
    require(len(materials) == 8, "EXACT_EIGHT_REQUIRED")
    records = {}
    for fact, expected, receipt, body, calendar in materials:
        require((expected.duration, expected.eps_basis, expected.statement_scope, expected.unit)
                == ("QUARTER", "BASIC", "CONSOLIDATED", "TWD/shares"),
                "FORMAL_EPS_EXPECTATION_INVALID")
        validate_fact_replay(fact, receipt, body, calendar)
        end = fact.period_end
        period = end[:4] + "Q" + str((int(end[5:7]) + 2) // 3)
        require(period not in records, "DUPLICATE_QUARTER")
        require(period in window, "QUARTER_OUTSIDE_REQUIRED_WINDOW")
        require(fact.symbol == index.symbol and fact.market == index.market,
                "QUALIFICATION_WRONG_ISSUER")
        try:
            value = Decimal(fact.normalized_value)
        except (InvalidOperation, TypeError, ValueError):
            require(False, "QUALIFICATION_NUMERIC_INVALID")
        require(value.is_finite(), "QUALIFICATION_NUMERIC_INVALID")
        # Multiple independent originals/branches are not a demonstrated revision chain.
        versions = sorted((v for v in index.versions if v.period == period),
                          key=lambda v: clock(v.public_at))
        for n, version in enumerate(versions):
            require(version.supersedes == (versions[n - 1].version_id if n else ""),
                    "REVISION_CONFLICT")
        proof = validate_pit(fact, expected, index, period, cutoff)
        selected = select_version(index, period, cutoff)
        records[period] = {"quarter": period, "value": fact.normalized_value,
                           "raw_sha256": fact.raw_sha256, "locator": fact.locator,
                           "receipt_reference": fact.receipt_reference,
                           "observed_at": fact.first_verified_observed_at,
                           "public_at": selected.public_at, "version_id": selected.version_id,
                           "proof": proof}
    require(set(records) == set(window), "REQUIRED_QUARTER_MISSING_NO_SUBSTITUTION")
    return {**BOUNDARY, "candidate_evidence_gates": "PASS", "anchor": anchor,
            "quarter_order": "LATEST_TO_OLDEST", "records": [records[q] for q in window],
            "activation": "NOT_AUTHORIZED"}
