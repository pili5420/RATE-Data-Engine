"""Offline G01 R5 semantic layers. Parses YAML; never executes workflow content.

R4 supplies exact source/blob and candidate-check provenance. R5 adds a separate
L1 syntax layer. L2 effects and L3 authority remain unqualified by construction.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import yaml

VERSION = "G01_R5_STATIC_SEMANTIC_ORACLE_V1"
COMMIT = "0334d18bde3bbc8ba0176ab2a51a5d07881e2bd7"
TREE = "dbeeb2cc67b43d4d9600b1f7eacee8ba8bdec820"
EXPECTED_BUNDLE_SHA256 = "9fb7afb8292b040b5964085423e15fe360a47bc79cab4ccec989445bcdd286a4"
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.S)
REF_EQUALITY = re.compile(
    r"^github\.ref\s*(==|!=)\s*(['\"])(refs/(?:heads|tags)/[^'\"\s]+)\2$"
)
SIMPLE_COMMAND = re.compile(r"^(?:echo|printf|true|false|exit\s+[0-9]+)(?:\s+[^;&|`$<>]*)?$", re.I)
SECRET_NAME = re.compile(r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE[_-]?KEY|AUTH)", re.I)
CONTEXT = re.compile(r"(?<![\w.])(?:github|matrix|needs|inputs|steps|env|runner|secrets|strategy|job|vars)\.[A-Za-z_]")


class Blocked(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Blocked(reason)


class UniqueBaseLoader(yaml.BaseLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            require(key not in result, "BLOCKED_DUPLICATE_YAML_KEY")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse(raw: bytes) -> dict:
    try:
        value = yaml.load(raw.decode("utf-8-sig"), Loader=UniqueBaseLoader)
    except Blocked:
        raise
    except (UnicodeError, yaml.YAMLError, ValueError) as exc:
        raise Blocked("BLOCKED_INVALID_YAML") from exc
    require(isinstance(value, dict), "BLOCKED_YAML_ROOT")
    return value


def classify_condition(value) -> dict:
    if value is None:
        return {"state": "L1_ABSENT"}
    require(isinstance(value, str) and value.strip(), "BLOCKED_INVALID_CONDITION")
    text = value.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    if text.lower() in ("true", "false"):
        return {"state": "L1_STATIC_BOOLEAN", "value": text.lower() == "true"}
    match = REF_EQUALITY.fullmatch(text)
    if match:
        return {"state": "L1_STATIC_REF_PREDICATE", "operator": match[1], "ref": match[3]}
    return {"state": "L1_UNRESOLVED_CONDITION", "reason": "DYNAMIC_OR_UNSUPPORTED_EXPRESSION"}


def evaluate_ref_condition(classified: dict, event: str, branch: str | None) -> str:
    """Only push branch refs are derivable from these supplied arguments."""
    state = classified["state"]
    if state == "L1_STATIC_BOOLEAN":
        return "TRUE" if classified["value"] else "FALSE"
    if state != "L1_STATIC_REF_PREDICATE" or event != "push" or not branch:
        return "UNKNOWN"
    actual = "refs/heads/" + branch
    matched = actual == classified["ref"]
    return "TRUE" if matched == (classified["operator"] == "==") else "FALSE"


def classify_field(key: str, value, path: str) -> dict:
    if key == "if":
        finding = classify_condition(value)
    elif key == "env" and isinstance(value, dict):
        finding = {"state": "L1_LITERAL_MAPPING"}
    elif key in {"run", "runs-on", "uses", "needs", "matrix", "with"}:
        if isinstance(value, (dict, list)):
            children = json.dumps(value, sort_keys=True)
            state = "L1_UNRESOLVED_DYNAMIC" if EXPRESSION.search(children) else "L1_LITERAL_STRUCTURE"
            finding = {"state": state}
        elif isinstance(value, str) and value.strip():
            if EXPRESSION.search(value) or "${{" in value or CONTEXT.search(value):
                finding = {"state": "L1_UNRESOLVED_DYNAMIC"}
            elif key == "run":
                finding = {"state": "L1_LITERAL_COMMAND_TEXT",
                           "simple_syntax": bool(SIMPLE_COMMAND.fullmatch(value.strip()))}
            elif key == "uses":
                finding = {"state": "L1_LITERAL_REFERENCE_ONLY",
                           "reusable_workflow": "/.github/workflows/" in value}
            else:
                finding = {"state": "L1_LITERAL_VALUE"}
        else:
            finding = {"state": "L1_UNRESOLVED_TYPE"}
    else:
        if isinstance(value, str) and (EXPRESSION.search(value) or "${{" in value or CONTEXT.search(value)):
            finding = {"state": "L1_UNRESOLVED_DYNAMIC"}
        else:
            finding = {"state": "L1_LITERAL_VALUE"}
    finding.update({"field": path, "key": key})
    return finding


def scan_l1(doc: dict) -> list[dict]:
    findings = []

    def walk(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items():
                here = (*path, str(key))
                if key in {"if", "run", "runs-on", "uses", "needs", "matrix", "with", "env"}:
                    findings.append(classify_field(key, child, "/".join(here)))
                if "env" in path and isinstance(child, str) and SECRET_NAME.search(str(key)):
                    findings.append({"field": "/".join(here), "key": str(key),
                                     "state": "L1_CREDENTIAL_VALUE_UNQUALIFIED"})
                if isinstance(child, str) and ("${{" in child or CONTEXT.search(child)) and key not in {"if", "run", "runs-on", "uses", "needs", "matrix", "with"}:
                    findings.append(classify_field(str(key), child, "/".join(here)))
                walk(child, here)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, str(index)))

    walk(doc)
    return findings


def classify_workflow(raw: bytes, r4_row: dict) -> dict:
    require(hashlib.sha256(raw).hexdigest() == r4_row["sha256"], "BLOCKED_SOURCE_SHA256")
    doc = parse(raw)
    fields = scan_l1(doc)
    unresolved = [f for f in fields if f["state"].startswith("L1_UNRESOLVED")
                  or f["state"] == "L1_CREDENTIAL_VALUE_UNQUALIFIED"]
    return {"path": r4_row["path"], "blob": r4_row["blob"], "sha256": r4_row["sha256"],
            "r4_classification": r4_row["classification"],
            "l1_state": "L1_PARTIAL_OR_UNRESOLVED" if unresolved else "L1_STATIC_SYNTAX_ONLY",
            "l1_fields": fields, "l1_unresolved_count": len(unresolved),
            "l2_state": "L2_UNQUALIFIED_RUNTIME_EFFECTS",
            "l2_r4_dependency_count": len(r4_row["runtime_dependencies"]),
            "l2_r4_dependency_codes": sorted({d["code"] for d in r4_row["runtime_dependencies"]}),
            "l3_required_check": "CANDIDATE_UNVERIFIED",
            "l3_owner": "BLOCKED_UNKNOWN_OWNER"}


def build(r4: dict, source_workflows: Path) -> dict:
    source = r4["source"]
    require(source["commit"] == COMMIT and source["tree"] == TREE
            and source["bundle_sha256"] == EXPECTED_BUNDLE_SHA256, "BLOCKED_PROVENANCE")
    require(len(r4["workflows"]) == 156 and len(r4["paths"]) == 1055
            and len(r4["check_candidates"]) == 163, "BLOCKED_INPUT_COUNTS")
    require(len({w["path"] for w in r4["workflows"]}) == 156
            and len({p["path"] for p in r4["paths"]}) == 1055, "BLOCKED_DUPLICATE_INPUT")
    require(all(p["owner_authorization"] == "BLOCKED_UNKNOWN_OWNER"
                and p["required_check_configuration"] == "BLOCKED_UNKNOWN_REQUIRED_CHECK"
                for p in r4["paths"]), "BLOCKED_OWNER_AUTHORITY_INVENTION")
    require(all(c["status"] == "CANDIDATE_UNVERIFIED" for c in r4["check_candidates"]),
            "BLOCKED_CHECK_AUTHORITY_INVENTION")
    workflows = []
    for row in r4["workflows"]:
        path = source_workflows / Path(row["path"]).name
        require(path.is_file(), "BLOCKED_MISSING_SOURCE_YAML")
        workflows.append(classify_workflow(path.read_bytes(), row))
    summary = {"workflows": len(workflows), "paths": len(r4["paths"]),
               "check_candidates": len(r4["check_candidates"]),
               "l1_counts": dict(sorted(Counter(w["l1_state"] for w in workflows).items())),
               "l2_unqualified": sum(w["l2_state"] == "L2_UNQUALIFIED_RUNTIME_EFFECTS" for w in workflows),
               "l3_verified": 0, "unknown_owner_paths": len(r4["paths"])}
    result = {"oracle_version": VERSION, "source": source, "summary": summary,
              "workflows": workflows, "paths": r4["paths"],
              "check_candidates": r4["check_candidates"],
              "authority": {"required_checks": "BLOCKED_UNKNOWN_REQUIRED_CHECK",
                            "owner": "BLOCKED_UNKNOWN_OWNER", "reviewer": "UNASSIGNED"}}
    validate(result)
    return result


def verify_git_objects(repo: Path, r4: dict, source_workflows: Path) -> None:
    """Compare all tracked path OIDs and all 156 workflow bytes to original Git objects."""
    def git(*args):
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args],
                                capture_output=True)
        require(result.returncode == 0, "BLOCKED_GIT_OBJECT_READ")
        return result.stdout

    require(git("rev-parse", COMMIT + "^{tree}").decode().strip() == TREE,
            "BLOCKED_CONTROLLING_TREE")
    entries = {}
    for item in git("ls-tree", "-r", "-z", "--full-tree", COMMIT).split(b"\0"):
        if not item:
            continue
        meta, path = item.split(b"\t", 1)
        mode, kind, oid = meta.decode("ascii").split()
        require(kind == "blob", "BLOCKED_NON_BLOB_ENTRY")
        entries[path.decode("utf-8")] = oid
    require(len(entries) == 1055 and len(r4["paths"]) == 1055,
            "BLOCKED_TRACKED_PATH_COUNT")
    require(entries == {row["path"]: row["blob"] for row in r4["paths"]},
            "BLOCKED_TRACKED_BLOB_PROVENANCE")
    for row in r4["workflows"]:
        raw = git("cat-file", "blob", row["blob"])
        require(entries.get(row["path"]) == row["blob"]
                and hashlib.sha256(raw).hexdigest() == row["sha256"]
                and (source_workflows / Path(row["path"]).name).read_bytes() == raw,
                "BLOCKED_WORKFLOW_BLOB_PROVENANCE")


def validate(result: dict) -> None:
    rows, paths, checks, summary = (result[k] for k in ("workflows", "paths", "check_candidates", "summary"))
    require(result["oracle_version"] == VERSION and result["source"]["commit"] == COMMIT
            and result["source"]["tree"] == TREE, "BLOCKED_ORACLE_PROVENANCE")
    require(len(rows) == len({x["path"] for x in rows}) == 156, "BLOCKED_WORKFLOW_ROWS")
    require(len(paths) == len({x["path"] for x in paths}) == 1055, "BLOCKED_PATH_ROWS")
    require(len(checks) == len({(x["workflow"], x["job_id"]) for x in checks}) == 163,
            "BLOCKED_CHECK_ROWS")
    require(all(x["status"] == "CANDIDATE_UNVERIFIED" for x in checks), "BLOCKED_CHECK_PROMOTION")
    require(all(x["owner_authorization"] == "BLOCKED_UNKNOWN_OWNER" for x in paths), "BLOCKED_OWNER_PROMOTION")
    require(all(x["l2_state"] == "L2_UNQUALIFIED_RUNTIME_EFFECTS" and x["l3_required_check"] == "CANDIDATE_UNVERIFIED"
                and x["l3_owner"] == "BLOCKED_UNKNOWN_OWNER" for x in rows), "BLOCKED_LAYER_PROMOTION")
    require(summary == {"workflows": len(rows), "paths": len(paths), "check_candidates": len(checks),
                        "l1_counts": dict(sorted(Counter(x["l1_state"] for x in rows).items())),
                        "l2_unqualified": len(rows), "l3_verified": 0,
                        "unknown_owner_paths": len(paths)}, "BLOCKED_CONTRADICTORY_SUMMARY")


def write(result: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "r5_oracle.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(result["summary"], indent=2) + "\n", encoding="utf-8")
    with (output / "workflow_classification_156.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "blob", "r4_classification", "l1_state",
                                                  "l1_unresolved_count", "l2_state", "l2_r4_dependency_count",
                                                  "l3_required_check", "l3_owner"])
        writer.writeheader()
        writer.writerows({k: row[k] for k in writer.fieldnames} for row in result["workflows"])
    with (output / "classification_diff_156.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "r4_classification", "r5_l1_state",
                                                  "r5_l2_state", "r5_l3_required_check"])
        writer.writeheader()
        writer.writerows({"path": row["path"], "r4_classification": row["r4_classification"],
                          "r5_l1_state": row["l1_state"], "r5_l2_state": row["l2_state"],
                          "r5_l3_required_check": row["l3_required_check"]} for row in result["workflows"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r4-oracle", type=Path, required=True)
    parser.add_argument("--source-workflows", type=Path, required=True)
    parser.add_argument("--readback-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    r4 = json.loads(args.r4_oracle.read_text(encoding="utf-8"))
    verify_git_objects(args.readback_repo, r4, args.source_workflows)
    result = build(r4, args.source_workflows)
    write(result, args.output)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
