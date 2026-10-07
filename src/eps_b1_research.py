"""Offline B1 presentation only. Production must never import this module."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re

from scripts.replay_eps_duration_proof import ARCHIVE_SHA, replay
from .eps_duration_facts.model import Expectation, Fact, Rejected, validate_semantics
from .eps_duration_facts.pit import clock, observed_forward_only

SCHEMA = "RATE-EPS-B1-RESEARCH-VIEW-V1"
MANIFEST = "RATE-EPS-B1-RESEARCH-MANIFEST-V1"
SCOPE = "NONDECISION_RESEARCH_ONLY"
ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT_NAME = "rate-eps-b1-research"
PROTECTED = {".git", ".github", "artifacts", "data", "src", "scripts", "tests", "config",
             "control", "control_center", "production", "live", "latest", "portfolio", "ledger",
             "history_acceptance", "decision_state", "state", "live_state", "state_latest",
             "rate_state_latest", "roy_portfolio", "ai_paper_portfolio", "transaction_ledger"}
BOUNDARY = {"usage_scope": SCOPE, "decision_eligible": False, "production_eligible": False,
            "original_eight_quarter_coverage_credit": 0}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


def source_manifest(archive):
    import zipfile
    with zipfile.ZipFile(archive) as source:
        inventory = source.read("inventory.json")
    return {"archive_reference": "tests/fixtures/eps_duration/official-proof.zip",
            "archive_sha256": ARCHIVE_SHA, "inventory_sha256": digest(inventory),
            "authority": "EXISTING_HASH_PINNED_DIAGNOSTIC_MATERIAL_NOT_PRODUCTION_INPUT"}


def build_view(archive, observation_cutoff, code_sha, *, generated_at=None):
    cutoff = clock(observation_cutoff)
    require(re.fullmatch(r"[0-9a-f]{40}", code_sha) is not None, "B1_CODE_SHA_INVALID")
    material = replay(archive)
    facts, excluded, quarantine = [], [], []
    for prefix, audit in material["audit"].items():
        for receipt, reason in audit["source_binding_rejections"].items():
            quarantine.append({"receipt_reference": receipt, "raw_integrity_status": "FAIL",
                               "reason": reason, "verified_numeric_value": None})
        completed = {r for receipts in audit["body_to_receipts"].values() for r in receipts}
        for receipt in audit["receipt_sha256"]:
            if receipt not in completed:
                quarantine.append({"receipt_reference": receipt, "raw_integrity_status": "FAIL",
                                   "reason": "COMPLETED_RESPONSE_UNPROVEN", "verified_numeric_value": None})
    for document in material["filings"]:
        for serialized in document["facts"]:
            # These facts come only from exact pinned raw-byte replay, not caller-supplied JSON.
            fact = Fact(**{k: v for k, v in serialized.items()
                           if k not in ("production_eligible", "original_eight_quarter_coverage_credit")})
            identity = digest(canonical({"receipt": document["receipt"], "raw": fact.raw_sha256,
                                         "locator": fact.locator}))
            try:
                validate_semantics(fact, Expectation(fact.symbol, fact.market, fact.period_start,
                    fact.period_end, fact.duration, fact.eps_basis))
            except Rejected as exc:
                quarantine.append({"fact_id": identity, "symbol": fact.symbol,
                    "receipt_reference": document["receipt"], "raw_integrity_status": fact.raw_integrity_status,
                    "fact_semantics_status": "UNPROVEN", "reason": str(exc), "verified_numeric_value": None})
                continue
            if clock(fact.first_verified_observed_at) > cutoff:
                excluded.append({"fact_id": identity, "symbol": fact.symbol, "market": fact.market,
                    "period_start": fact.period_start, "period_end": fact.period_end,
                    "first_verified_observed_at": fact.first_verified_observed_at,
                    "reason": "OBSERVATION_AFTER_CUTOFF", "verified_numeric_value": None})
                continue
            observed = observed_forward_only(fact, observation_cutoff)
            facts.append({"fact_id": identity, **asdict(fact), "source": "MOPS_INLINE_XBRL",
                          "archive_receipt_reference": document["receipt"],
                          "historical_pit_status": observed["historical_pit_status"],
                          "latest_version_status": "UNPROVEN", **BOUNDARY})
    audits = material["audit"]
    bodies = {h for audit in audits.values() for h in audit["body_to_receipts"]}
    summary = {
        "source_case_symbols": ["2330", "6488", "1340"],
        "fact_evaluated_symbols": ["2330", "6488"],
        "source_evidence_only_symbols": ["1340"],
        "expected_universe": {"TWSE": 1085, "TPEX": 893, "total": 1978},
        "not_evaluated_symbol_count": 1976,
        "not_evaluated_scope": "ALL_OTHER_EXPECTED_UNIVERSE_MEMBERS_INCLUDING_1340_FACTS",
        "not_evaluated_status": "NOT_EVALUATED",
        "receipt_count": sum(a["receipt_count"] for a in audits.values()),
        "complete_response_count": sum(a["completed_responses"] for a in audits.values()),
        "failed_response_count": sum(a["failed_responses"] for a in audits.values()),
        "failed_transport_attempt_count": sum(a["failed_attempts"] for a in audits.values()),
        "unique_body_count": len(bodies),
        "replayed_eps_document_count": len(material["filings"]),
        "replayed_fact_count": sum(len(d["facts"]) for d in material["filings"]),
        "displayed_fact_count": len(facts), "excluded_observation_count": len(excluded),
        "quarantine_count": len(quarantine),
        "historical_pit_unproven_fact_count": len(facts),
        "official_public_version_identity_verified_count": 0,
        "original_eight_quarter_coverage": "0/1978",
        "limits": ["Case study, not full-market coverage; receipts are not filing/version counts",
                   "1340 PDF source evidence retained but not automatically extracted as facts",
                   "No exact historical-public-version or complete filing/correction index proof",
                   "No latest-version claim; no BASIC/DILUTED or duration merge; no EPS derivation"],
    }
    core = {"schema_version": SCHEMA, "artifact": "RATE_EPS_B1_RESEARCH_VIEW", **BOUNDARY,
        "historical_cutoff": "2026-10-05", "observation_cutoff": observation_cutoff,
        "source_manifest": source_manifest(archive),
        "implementation_sha256": digest(Path(__file__).read_bytes()),
        "summary": summary, "facts": facts, "excluded_observations": excluded, "quarantine": quarantine}
    now = generated_at or datetime.now(timezone.utc).isoformat()
    clock(now)
    return {"core": core, "core_sha256": digest(canonical(core)),
            "code_sha": code_sha, "generated_at": now, **BOUNDARY}


def validate_view(value, archive, *, expected_code_sha=None):
    try:
        if expected_code_sha is not None:
            require(value["code_sha"] == expected_code_sha, "B1_CODE_SHA_BINDING_INVALID")
        expected = build_view(archive, value["core"]["observation_cutoff"], value["code_sha"],
                              generated_at=value["generated_at"])
        require(canonical(value) == canonical(expected), "B1_SERIALIZED_MATERIAL_TAMPERED")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, Rejected):
            raise
        raise Rejected("B1_ENVELOPE_INVALID") from exc
    return "PASS_NONDECISION_ONLY"


def markdown_view(value):
    core = value["core"]
    def safe(item):
        return html.escape("未知" if item is None else str(item)).replace("|", "&#124;").replace("\n", " ")
    lines = ["# RATE EPS B1 研究證據視圖", "", "用途：NONDECISION_RESEARCH_ONLY。不得用於排名、評分、買賣或正式 coverage。",
        "", "decision_eligible=false；production_eligible=false；原八季 coverage credit=0。",
        "", f"觀察 cutoff：{safe(core['observation_cutoff'])}；原歷史 cutoff：2026-10-05（未修改）。",
        f"程式 commit：{value['code_sha']}；生成時間：{safe(value['generated_at'])}。",
        f"核心 SHA256：{value['core_sha256']}；來源封存 SHA256：{ARCHIVE_SHA}。", "", "## 範圍與限制", ""]
    summary = core["summary"]
    lines.extend([f"來源案例：2330、6488、1340；fact 評估僅 2330／6488；1340 為來源證據、fact 未評估。",
        f"receipt {summary['receipt_count']}；unique body {summary['unique_body_count']}；EPS 文件 {summary['replayed_eps_document_count']}；重播 fact {summary['replayed_fact_count']}。",
        f"本次展示 {summary['displayed_fact_count']}；觀察 cutoff 排除 {summary['excluded_observation_count']}；隔離 {summary['quarantine_count']}；Historical PIT 未證明 {summary['historical_pit_unproven_fact_count']}。",
        "1085 + 893 = 1978 的正式 universe 不變；其餘 1976 家 fact 狀態為 NOT_EVALUATED，未逐家公司盤點或宣稱全市場覆蓋。",
        "receipt 不等於 filing；文件 hash 不等於公開版本 identity。首次驗證觀察時間不是首次公開時間。",
        "QUARTER／YEAR_TO_DATE／ANNUAL 與 BASIC／DILUTED 分別展示，不合併、不衍生；未證明 latest。", "", "## Facts", ""])
    for fact in core["facts"]:
        lines.extend([f"### {safe(fact['symbol'])} / {safe(fact['market'])} / {safe(fact['duration'])} / {safe(fact['eps_basis'])}",
            f"- issuer：{safe(fact['issuer_identity'])}；期間：{fact['period_start']} 至 {fact['period_end']}。",
            f"- concept：{safe(fact['concept'])}；scope：{safe(fact['statement_scope'])}；unit：{safe(fact['unit'])}。",
            f"- raw：{safe(fact['raw_value'])}；normalized：{safe(fact['normalized_value'])}；scale：{safe(fact['scale'])}；decimals：{safe(fact['decimals'])}；precision：{safe(fact['precision'])}。",
            f"- source：{safe(fact['source_representation'])}；document：{fact['document_identity']}；filing：{safe(fact['filing_identity'])}；revision：{safe(fact['revision_identity'])}。",
            f"- raw hash：{fact['raw_sha256']}；receipt：{safe(fact['archive_receipt_reference'])}；context：{safe(fact['context_reference'])}；locator：{safe(fact['locator'])}。",
            f"- first_verified_observed_at：{safe(fact['first_verified_observed_at'])}。",
            f"- 公開時間：{safe(fact['source_publication_time'])}；精度：{fact['publication_precision']}；證據：{safe(fact['publication_evidence'])}。",
            f"- Raw integrity：{fact['raw_integrity_status']}；Fact semantics：{fact['fact_semantics_status']}；Historical PIT：{fact['historical_pit_status']}；latest version：UNPROVEN。",
            "- NONDECISION_RESEARCH_ONLY；decision_eligible=false；production_eligible=false；原八季 coverage credit=0。", ""])
    lines.extend(["## 隔離／錯誤（不展示為已驗證數值）", ""])
    for item in core["quarantine"]:
        lines.append(f"- {safe(item.get('receipt_reference'))}：{safe(item['reason'])}；verified_numeric_value=null。")
    lines.extend(["", "## cutoff 排除的觀察（無數值展示）", ""])
    for item in core["excluded_observations"]:
        lines.append(f"- {item['symbol']}：{item['first_verified_observed_at']}；OBSERVATION_AFTER_CUTOFF。")
    return "\n".join(lines) + "\n"


def _safe_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink() and not (hasattr(part, "is_junction") and part.is_junction()),
                "B1_OUTPUT_LINK_FORBIDDEN")
        require(part.name.casefold() not in PROTECTED and not part.name.upper().startswith("RATE_PRODUCTION"),
                "B1_PROTECTED_NAMESPACE")
        require(not (part / ".git").exists(), "B1_OUTPUT_INSIDE_REPOSITORY")
    resolved = path.resolve()
    require(resolved != ROOT and ROOT not in resolved.parents, "B1_OUTPUT_INSIDE_REPOSITORY")
    return resolved


def _manifest(value, payloads):
    manifest = {"schema_version": MANIFEST, "artifact": "RATE_EPS_B1_RESEARCH_MANIFEST", **BOUNDARY,
        "source_manifest": value["core"]["source_manifest"], "core_sha256": value["core_sha256"],
        "code_sha": value["code_sha"], "generated_at": value["generated_at"],
        "observation_cutoff": value["core"]["observation_cutoff"], "files": {k: digest(v) for k, v in payloads.items()},
        "validation": {"raw_replay": "PASS", "fact_semantics": "PER_FACT_STATUS_REQUIRED",
                       "historical_pit": "UNPROVEN", "delivery": "NONDECISION_ONLY"}}
    manifest["manifest_sha256"] = digest(canonical(manifest))
    return manifest


def export_view(value, archive, research_root, output_dir):
    validate_view(value, archive)
    root, destination = _safe_path(research_root), _safe_path(output_dir)
    require(root.name.casefold() == RESEARCH_ROOT_NAME, "B1_DEDICATED_ROOT_REQUIRED")
    require(destination != root and destination.is_relative_to(root), "B1_OUTPUT_PATH_ESCAPE")
    require(not destination.exists(), "B1_OUTPUT_ALREADY_EXISTS")
    root.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=False)
    _safe_path(destination)
    payloads = {"RATE_EPS_B1_RESEARCH_VIEW.json": canonical(value) + b"\n",
                "RATE_EPS_B1_RESEARCH_VIEW.zh-TW.md": markdown_view(value).encode("utf-8")}
    manifest = _manifest(value, payloads)
    payloads["RATE_EPS_B1_RESEARCH_MANIFEST.json"] = canonical(manifest) + b"\n"
    for name, data in payloads.items():
        target = _safe_path(destination / name)
        require(target.parent == destination, "B1_OUTPUT_PATH_ESCAPE")
        with target.open("xb") as stream:
            stream.write(data)
    return manifest


def verify_export(directory, archive, *, expected_code_sha=None):
    directory = _safe_path(directory)
    manifest = json.loads((directory / "RATE_EPS_B1_RESEARCH_MANIFEST.json").read_text(encoding="utf-8"))
    expected_names = ("RATE_EPS_B1_RESEARCH_VIEW.json", "RATE_EPS_B1_RESEARCH_VIEW.zh-TW.md")
    require(sorted(manifest.get("files", {})) == sorted(expected_names), "B1_MANIFEST_FILES_INVALID")
    identity = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    require(digest(canonical(identity)) == manifest.get("manifest_sha256"), "B1_MANIFEST_TAMPERED")
    for name in expected_names:
        path = _safe_path(directory / name)
        require(path.parent == directory and digest(path.read_bytes()) == manifest["files"][name],
                "B1_OUTPUT_HASH_MISMATCH")
    value = json.loads((directory / expected_names[0]).read_text(encoding="utf-8"))
    validate_view(value, archive, expected_code_sha=expected_code_sha)
    require((directory / expected_names[1]).read_bytes() == markdown_view(value).encode("utf-8"),
            "B1_MARKDOWN_MATERIAL_TAMPERED")
    for field in (*BOUNDARY, "code_sha", "generated_at", "core_sha256"):
        require(canonical(manifest.get(field)) == canonical(value[field]), "B1_MANIFEST_BINDING_INVALID")
    require(manifest.get("schema_version") == MANIFEST
            and manifest.get("source_manifest") == value["core"]["source_manifest"]
            and manifest.get("observation_cutoff") == value["core"]["observation_cutoff"],
            "B1_MANIFEST_BINDING_INVALID")
    payloads = {name: (directory / name).read_bytes() for name in expected_names}
    require(canonical(manifest) == canonical(_manifest(value, payloads)), "B1_MANIFEST_BINDING_INVALID")
    return "PASS_NONDECISION_ONLY"
