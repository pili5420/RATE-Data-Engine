"""Syntax/AST review for an in-memory RATE intraday activation candidate.

This validator compiles candidate Python, parses scheduler YAML, checks selected
AST invariants, and performs no writes or activation actions.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from .intraday_activation_delta_plan import NEW_RUNTIME_FILES
from .intraday_activation_readiness import ALLOWED_EXISTING_MUTATION_PATHS

ROOT = Path(__file__).resolve().parents[1]
PYTHON_PATHS = (
    "src/phase2_production.py",
    "scripts/build_phase2_production_source.py",
    "src/intraday_provider_runtime.py",
    "scripts/acquire_intraday_provider_feed.py",
)
WORKFLOW_PATHS = (
    ".github/workflows/rate_production_0930_scheduler.yml",
    ".github/workflows/rate_production_1200_scheduler.yml",
)
JSON_PATHS = (
    "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json",
    "config/SOURCE_REGISTRY.json",
    "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json",
)


class ActivationCandidateSyntaxError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationCandidateSyntaxError(reason)


def _parse_python(path: str, text: str) -> ast.Module:
    try:
        return ast.parse(text, filename=path)
    except SyntaxError as exc:
        raise ActivationCandidateSyntaxError(
            "ACTIVATION_SYNTAX_PYTHON_INVALID:" + path
        ) from exc


def _parse_yaml(path: str, text: str) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ActivationCandidateSyntaxError(
            "ACTIVATION_SYNTAX_YAML_INVALID:" + path
        ) from exc
    require(isinstance(value, Mapping), "ACTIVATION_SYNTAX_YAML_NOT_OBJECT:" + path)
    return value


def _constant_assignments(tree: ast.AST) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                out[target.id] = node.value.value
    return out


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _contains_print(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node) == "print"
        for node in ast.walk(tree)
    )


def _contains_call(tree: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node) in names
        for node in ast.walk(tree)
    )


def _validate_phase2_ast(tree: ast.Module) -> None:
    functions = _functions(tree)
    for name in (
        "require_intraday_authority",
        "intraday_decision_gate_status",
        "validate_phase2_source_bundle",
        "validate_transition",
        "decision_from_evaluation",
    ):
        require(name in functions, "ACTIVATION_SYNTAX_PHASE2_FUNCTION_MISSING:" + name)

    helper = functions["intraday_decision_gate_status"]
    returns = [node for node in ast.walk(helper) if isinstance(node, ast.Return)]
    require(len(returns) == 1 and isinstance(returns[0].value, ast.IfExp),
            "ACTIVATION_SYNTAX_PHASE2_STATUS_HELPER_INVALID")
    branch = returns[0].value
    require(
        isinstance(branch.body, ast.Constant) and branch.body.value == "PASS"
        and isinstance(branch.orelse, ast.Constant) and branch.orelse.value == "NOT_APPLICABLE",
        "ACTIVATION_SYNTAX_PHASE2_STATUS_HELPER_INVALID",
    )
    require(isinstance(branch.test, ast.Compare)
            and isinstance(branch.test.left, ast.Name)
            and branch.test.left.id == "cadence"
            and len(branch.test.ops) == 1
            and isinstance(branch.test.ops[0], ast.In),
            "ACTIVATION_SYNTAX_PHASE2_STATUS_HELPER_INVALID")
    comparator = branch.test.comparators[0]
    require(isinstance(comparator, (ast.Set, ast.Tuple, ast.List)),
            "ACTIVATION_SYNTAX_PHASE2_STATUS_HELPER_INVALID")
    values = {
        item.value for item in comparator.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }
    require(values == {"09:30", "12:00"},
            "ACTIVATION_SYNTAX_PHASE2_STATUS_HELPER_INVALID")


def _validate_runtime_ast(tree: ast.Module, secret_name: str, provider_name: str) -> None:
    assignments = _constant_assignments(tree)
    require(assignments.get("MAX_REQUESTS") == 30,
            "ACTIVATION_SYNTAX_RUNTIME_MAX_REQUESTS_INVALID")
    require(assignments.get("MAX_RETRIES") == 0,
            "ACTIVATION_SYNTAX_RUNTIME_MAX_RETRIES_INVALID")
    require(assignments.get("FALLBACK_ALLOWED") is False,
            "ACTIVATION_SYNTAX_RUNTIME_FALLBACK_INVALID")
    require(assignments.get("SECRET_NAME") == secret_name,
            "ACTIVATION_SYNTAX_RUNTIME_SECRET_NAME_INVALID")
    if provider_name.lower() == "fugle":
        require(assignments.get("API_HOST") == "api.fugle.tw",
                "ACTIVATION_SYNTAX_RUNTIME_HOST_INVALID")
    require("acquire_intraday_feed" in _functions(tree),
            "ACTIVATION_SYNTAX_RUNTIME_FUNCTION_MISSING")
    require(not any(isinstance(node, ast.While) for node in ast.walk(tree)),
            "ACTIVATION_SYNTAX_RUNTIME_WHILE_LOOP_FORBIDDEN")
    require(not _contains_call(tree, {"time.sleep", "sleep"}),
            "ACTIVATION_SYNTAX_RUNTIME_SLEEP_FORBIDDEN")
    require(not _contains_print(tree), "ACTIVATION_SYNTAX_RUNTIME_PRINT_FORBIDDEN")


def _validate_acquisition_ast(tree: ast.Module, secret_name: str) -> None:
    assignments = _constant_assignments(tree)
    require(assignments.get("SECRET_NAME") == secret_name,
            "ACTIVATION_SYNTAX_ACQUISITION_SECRET_NAME_INVALID")
    require("main" in _functions(tree), "ACTIVATION_SYNTAX_ACQUISITION_MAIN_MISSING")
    require(not _contains_print(tree), "ACTIVATION_SYNTAX_ACQUISITION_PRINT_FORBIDDEN")

    getenv_ok = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "os.getenv" or not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Name) and arg.id == "SECRET_NAME":
            getenv_ok = True
        if isinstance(arg, ast.Constant) and arg.value == secret_name:
            getenv_ok = True
    require(getenv_ok, "ACTIVATION_SYNTAX_ACQUISITION_SECRET_READ_MISSING")


def _cron(text: str) -> str:
    match = re.search(r'cron:\s*["\']?([^"\'\n]+)', text)
    require(match is not None, "ACTIVATION_SYNTAX_SCHEDULER_CRON_MISSING")
    return match.group(1).strip()


def _walk_mapping(value: Any):
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _walk_mapping(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_mapping(item)


def _validate_workflow(
    path: str,
    text: str,
    *,
    cadence: str,
    secret_name: str,
) -> None:
    value = _parse_yaml(path, text)
    job_name = "production-" + cadence.replace(":", "")
    jobs = value.get("jobs")
    require(isinstance(jobs, Mapping) and job_name in jobs,
            "ACTIVATION_SYNTAX_SCHEDULER_JOB_MISSING:" + cadence)
    job = jobs[job_name]
    require(isinstance(job, Mapping), "ACTIVATION_SYNTAX_SCHEDULER_JOB_INVALID:" + cadence)
    env = job.get("env")
    require(isinstance(env, Mapping), "ACTIVATION_SYNTAX_SCHEDULER_ENV_MISSING:" + cadence)
    require(env.get(secret_name) == "${{ secrets." + secret_name + " }}",
            "ACTIVATION_SYNTAX_SCHEDULER_SECRET_EXPRESSION_INVALID:" + cadence)
    require(
        env.get("RATE_AUTHORIZED_INTRADAY_FEED_PATH")
        == f"artifacts/production_{cadence.replace(':', '')}/RATE_AUTHORIZED_INTRADAY_FEED.json",
        "ACTIVATION_SYNTAX_SCHEDULER_FEED_PATH_INVALID:" + cadence,
    )
    steps = job.get("steps")
    require(isinstance(steps, list), "ACTIVATION_SYNTAX_SCHEDULER_STEPS_INVALID:" + cadence)
    commands = "\n".join(
        str(step.get("run", "")) for step in steps if isinstance(step, Mapping)
    )
    for required in (
        "scripts/acquire_intraday_provider_feed.py",
        "scripts/build_phase2_production_source.py",
        "scripts/run_phase2_production.py",
    ):
        require(required in commands, "ACTIVATION_SYNTAX_SCHEDULER_COMMAND_MISSING:" + cadence)
    for mapping in _walk_mapping(value):
        require(mapping.get("continue-on-error") is not True,
                "ACTIVATION_SYNTAX_SCHEDULER_CONTINUE_ON_ERROR_FORBIDDEN:" + cadence)
    require("--public-official-partial" not in text,
            "ACTIVATION_SYNTAX_SCHEDULER_PUBLIC_PARTIAL_FORBIDDEN:" + cadence)

    current = (ROOT / path).read_text(encoding="utf-8")
    require(_cron(text) == _cron(current),
            "ACTIVATION_SYNTAX_SCHEDULER_CRON_DRIFT:" + cadence)


def validate_activation_candidate_syntax(
    candidate_files: Mapping[str, str],
    *,
    expected_provider_name: str,
    expected_secret_name: str,
) -> dict[str, Any]:
    expected_paths = set(ALLOWED_EXISTING_MUTATION_PATHS) | set(NEW_RUNTIME_FILES)
    require(isinstance(candidate_files, Mapping) and set(candidate_files) == expected_paths,
            "ACTIVATION_SYNTAX_CANDIDATE_FILE_SET_INVALID")
    require(isinstance(expected_provider_name, str) and expected_provider_name.strip(),
            "ACTIVATION_SYNTAX_PROVIDER_INVALID")
    require(isinstance(expected_secret_name, str) and expected_secret_name.strip(),
            "ACTIVATION_SYNTAX_SECRET_NAME_INVALID")

    for path in JSON_PATHS:
        try:
            parsed = json.loads(candidate_files[path])
        except json.JSONDecodeError as exc:
            raise ActivationCandidateSyntaxError(
                "ACTIVATION_SYNTAX_JSON_INVALID:" + path
            ) from exc
        require(isinstance(parsed, dict), "ACTIVATION_SYNTAX_JSON_NOT_OBJECT:" + path)

    trees = {
        path: _parse_python(path, candidate_files[path])
        for path in PYTHON_PATHS
    }
    _validate_phase2_ast(trees["src/phase2_production.py"])
    require(
        "qualify_phase2_intraday_feed"
        in {
            alias.name
            for node in trees["scripts/build_phase2_production_source.py"].body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        },
        "ACTIVATION_SYNTAX_SOURCE_BUILDER_ADMISSION_IMPORT_MISSING",
    )
    _validate_runtime_ast(
        trees["src/intraday_provider_runtime.py"],
        expected_secret_name,
        expected_provider_name,
    )
    _validate_acquisition_ast(
        trees["scripts/acquire_intraday_provider_feed.py"],
        expected_secret_name,
    )

    _validate_workflow(
        WORKFLOW_PATHS[0],
        candidate_files[WORKFLOW_PATHS[0]],
        cadence="09:30",
        secret_name=expected_secret_name,
    )
    _validate_workflow(
        WORKFLOW_PATHS[1],
        candidate_files[WORKFLOW_PATHS[1]],
        cadence="12:00",
        secret_name=expected_secret_name,
    )

    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_SYNTAX_REVIEW_V1",
        "validation_status": "PASS",
        "python_files_compiled": list(PYTHON_PATHS),
        "yaml_files_parsed": list(WORKFLOW_PATHS),
        "json_files_parsed": list(JSON_PATHS),
        "provider_name": expected_provider_name,
        "secret_name": expected_secret_name,
        "repository_writes": 0,
        "network_requests": 0,
        "credential_access": 0,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }
