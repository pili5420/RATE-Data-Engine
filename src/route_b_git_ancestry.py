"""Build fail-closed Git ancestry evidence for Route B Production Acceptance."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping

from src.route_b_post_merge_activation import ALLOWED_POINTER_PREFIXES


class RouteBGitAncestryError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RouteBGitAncestryError(reason)


def _sha(value: Any) -> bool:
    return isinstance(value,str) and len(value)==40 and all(c in "0123456789abcdef" for c in value)


def _git(repo_root: Path, *args: str) -> str:
    run=subprocess.run(
        ["git","-C",str(repo_root),*args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode != 0:
        raise RouteBGitAncestryError("ROUTE_B_GIT_COMMAND_FAILED:"+args[0])
    return run.stdout.strip()


def _is_ancestor(repo_root: Path, base: str, head: str) -> bool:
    run=subprocess.run(
        ["git","-C",str(repo_root),"merge-base","--is-ancestor",base,head],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if run.returncode == 0:
        return True
    if run.returncode == 1:
        return False
    raise RouteBGitAncestryError("ROUTE_B_GIT_ANCESTRY_COMMAND_FAILED")


def _changed_paths(repo_root: Path, base: str, head: str) -> list[str]:
    text=_git(repo_root,"diff","--name-only",base+".."+head)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _authorized(paths: list[str]) -> bool:
    return all(
        any(path==prefix or path.startswith(prefix) for prefix in ALLOWED_POINTER_PREFIXES)
        for path in paths
    )


BASELINE_CONFIG_PATH="config/RATE_ROUTE_B_ACTIVATION_BASELINE_V1.json"


def resolve_activation_binding_sha(
    repo_root: str | Path,
    *,
    activation_merge_sha: str,
) -> str:
    root=Path(repo_root).resolve()
    require(root.is_dir(),"ROUTE_B_GIT_REPO_ROOT_INVALID")
    require(_sha(activation_merge_sha),"ROUTE_B_GIT_ACTIVATION_SHA_INVALID")
    _git(root,"cat-file","-e",activation_merge_sha+"^{commit}")
    binding=_git(root,"rev-list","-1","HEAD","--",BASELINE_CONFIG_PATH)
    require(_sha(binding),"ROUTE_B_GIT_BINDING_HISTORY_NOT_FOUND")
    require(_is_ancestor(root,activation_merge_sha,binding),
            "ROUTE_B_GIT_CODE_NOT_ANCESTOR_OF_BINDING")
    require(
        _changed_paths(root,activation_merge_sha,binding)==[BASELINE_CONFIG_PATH],
        "ROUTE_B_GIT_BINDING_DELTA_INVALID",
    )
    return binding

def build_ancestry_evidence(
    repo_root: str | Path,
    *,
    activation_merge_sha: str,
    source_heads: Mapping[str,str],
    activation_binding_sha: str | None = None,
) -> dict[str,Any]:
    root=Path(repo_root).resolve()
    require(root.is_dir(),"ROUTE_B_GIT_REPO_ROOT_INVALID")
    require(_sha(activation_merge_sha),"ROUTE_B_GIT_ACTIVATION_SHA_INVALID")
    require(isinstance(source_heads,Mapping) and source_heads,
            "ROUTE_B_GIT_SOURCE_HEADS_INVALID")
    if activation_binding_sha is not None:
        require(_sha(activation_binding_sha),"ROUTE_B_GIT_BINDING_SHA_INVALID")
        _git(root,"cat-file","-e",activation_merge_sha+"^{commit}")
        _git(root,"cat-file","-e",activation_binding_sha+"^{commit}")
        require(_is_ancestor(root,activation_merge_sha,activation_binding_sha),
                "ROUTE_B_GIT_CODE_NOT_ANCESTOR_OF_BINDING")
        binding_changes=_changed_paths(root,activation_merge_sha,activation_binding_sha)
        require(binding_changes==[BASELINE_CONFIG_PATH],
                "ROUTE_B_GIT_BINDING_DELTA_INVALID")
    else:
        binding_changes=[]
        activation_binding_sha=activation_merge_sha

    actual_head=_git(root,"rev-parse","HEAD")
    require(_sha(actual_head),"ROUTE_B_GIT_HEAD_INVALID")
    rows={}
    all_pass=True
    for label,head in source_heads.items():
        require(isinstance(label,str) and label,"ROUTE_B_GIT_SOURCE_LABEL_INVALID")
        require(_sha(head),"ROUTE_B_GIT_SOURCE_SHA_INVALID:"+str(label))
        _git(root,"cat-file","-e",activation_merge_sha+"^{commit}")
        _git(root,"cat-file","-e",head+"^{commit}")
        code_ancestor=_is_ancestor(root,activation_merge_sha,head)
        binding_ancestor=_is_ancestor(root,activation_binding_sha,head)
        changed=_changed_paths(root,activation_binding_sha,head) if binding_ancestor else []
        authorized=code_ancestor and binding_ancestor and _authorized(changed)
        rows[label]={
            "source_head_sha":head,
            "activation_is_ancestor":code_ancestor,
            "binding_is_ancestor":binding_ancestor,
            "changed_paths_since_activation":changed,
            "operational_changes_authorized":authorized,
        }
        all_pass=all_pass and authorized

    return {
        "artifact":"RATE_ROUTE_B_GIT_ANCESTRY_EVIDENCE_V1",
        "validation_status":"PASS" if all_pass else "FAIL_CLOSED",
        "activation_merge_sha":activation_merge_sha,
        "activation_binding_sha":activation_binding_sha,
        "binding_changed_paths":binding_changes,
        "evidence_builder_head_sha":actual_head,
        "source_heads":rows,
        "allowed_pointer_prefixes":list(ALLOWED_POINTER_PREFIXES),
        "unreviewed_code_change_allowed":False,
        "fallback_allowed":False,
    }
