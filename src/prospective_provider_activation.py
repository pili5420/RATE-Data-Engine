"""Main-commit authorization seal. Never infer activation from acquisition time."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .full_market_history import put_bytes
from .provider_eps_candidate import _canonical, _time
from .provider_eps_metadata import read_metadata
from .provider_financial_features import within_git_checkout

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = "docs/contracts/RATE_PROSPECTIVE_PROVIDER_ACTIVATION_V1.json"
CONTRACT = read_metadata((ROOT / CONTRACT_PATH).read_bytes())
REPOSITORY = "pili5420/RATE-Data-Engine"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main_binding(commit, main_sha, contract_sha256):
    """A caller must fetch main first; neither a PR head nor a local branch is main."""
    require(all(isinstance(s, str) and len(s) == 40 and set(s) <= set("0123456789abcdef")
        for s in (commit, main_sha)), "ACTIVATION_COMMIT_INVALID")
    current_main = git("rev-parse", "origin/main").decode().strip()
    require(subprocess.run(["git", "merge-base", "--is-ancestor", main_sha, current_main], cwd=ROOT,
        capture_output=True).returncode == 0, "ACTIVATION_MAIN_PIN_MISMATCH")
    require(subprocess.run(["git", "merge-base", "--is-ancestor", commit, main_sha], cwd=ROOT,
        capture_output=True).returncode == 0, "ACTIVATION_COMMIT_NOT_ON_MAIN")
    blob = git("show", commit + ":" + CONTRACT_PATH)
    require(sha256(blob) == contract_sha256 and read_metadata(blob) == CONTRACT, "ACTIVATION_MAIN_CONTRACT_MISMATCH")
    # A later main commit must not move the original activation boundary.
    parents = git("rev-list", "--parents", "-n", "1", commit).decode().split()[1:]
    for parent in parents:
        prior = subprocess.run(["git", "cat-file", "-e", parent + ":" + CONTRACT_PATH], cwd=ROOT, capture_output=True)
        require(prior.returncode != 0, "ACTIVATION_NOT_FIRST_AUTHORIZATION_COMMIT")
    return git("show", "-s", "--format=%cI", commit).decode().strip()


def authorization(proof, proof_sha256, receipt, receipt_sha256, main_sha, validated_at):
    """The proof hash is a Control Center/trusted acquisition pin, not self-trust."""
    require(sha256(proof) == proof_sha256 and sha256(receipt) == receipt_sha256, "ACTIVATION_PROOF_TAMPER")
    pr, r = read_metadata(proof), read_metadata(receipt)
    require(pr["base"]["repo"]["full_name"] == REPOSITORY and pr["base"]["ref"] == "main" and
        pr["merged"] is True and pr["merged_at"] is not None, "ACTIVATION_NOT_MERGED_TO_MAIN")
    url = "https://api.github.com/repos/" + REPOSITORY + "/pulls/" + str(pr["number"])
    require(r["endpoint"] == r["final_url"] == url and r["http_status"] == 200 and
        r["raw_sha256"] == proof_sha256 and r["bytes"] == len(proof) and r["attempts"] == 1 and
        r["fallback_used"] is False, "ACTIVATION_PROOF_RECEIPT_INVALID")
    require(CONTRACT["activation_timestamp"] is None and CONTRACT["provider_authorization"] == "AUTHORIZED_PROSPECTIVE_ONLY",
        "ACTIVATION_CONTRACT_INVALID")
    commit = pr["merge_commit_sha"]
    require(isinstance(commit, str) and len(commit) == 40 and set(commit) <= set("0123456789abcdef"), "ACTIVATION_COMMIT_INVALID")
    contract_bytes = git("show", commit + ":" + CONTRACT_PATH)
    commit_time = main_binding(commit, main_sha, sha256(contract_bytes))
    activation = pr["merged_at"]
    require(_time(commit_time) <= _time(activation) <= _time(r["requested_at"]) <= _time(r["received_at"]) <=
        _time(validated_at) <= datetime.now(timezone.utc), "ACTIVATION_EFFECTIVE_TIME_INVALID")
    core = {"artifact_kind": "RATE_PROSPECTIVE_PROVIDER_ACTIVATION_AUTHORITY_V1", "contract": deepcopy(CONTRACT),
        "authorization_commit": commit, "verified_main_sha": main_sha, "contract_git_blob_sha256": sha256(contract_bytes),
        "activation_timestamp": activation, "effective_time_source": "GITHUB_MERGED_AT_NOT_GIT_AUTHOR_DATE",
        "proof_sha256": proof_sha256, "proof_receipt_sha256": receipt_sha256, "validated_at": validated_at}
    return {**core, "authority_id": "provider-activation-" + sha256(_canonical(core))}


def seal(root, proof, proof_sha256, receipt, receipt_sha256, main_sha, validated_at):
    root = Path(root).absolute()
    require(not within_git_checkout(root) and not any(p.casefold() in {"production", "latest", "state", "portfolio",
        "ledger", "artifacts", "snapshots", "data"} for p in root.parts), "ACTIVATION_PROTECTED_OUTPUT")
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (root, *root.parents)),
        "ACTIVATION_LINKED_OUTPUT")
    authority = authorization(proof, proof_sha256, receipt, receipt_sha256, main_sha, validated_at)
    root.mkdir(parents=True, exist_ok=True)
    # One well-known immutable slot: a new proof cannot silently replace an old seal.
    put_bytes(root, "ACTIVATION.json", _canonical(authority))
    put_bytes(root, "authorization-proof.json", proof)
    put_bytes(root, "authorization-receipt.json", receipt)
    return sha256((root / "ACTIVATION.json").read_bytes())


def load(root, trusted_sha256):
    root = Path(root)
    body = (root / "ACTIVATION.json").read_bytes()
    require(sha256(body) == trusted_sha256, "ACTIVATION_SEAL_TAMPER")
    saved = read_metadata(body)
    reconstructed = authorization((root / "authorization-proof.json").read_bytes(), saved["proof_sha256"],
        (root / "authorization-receipt.json").read_bytes(), saved["proof_receipt_sha256"],
        saved["verified_main_sha"], saved["validated_at"])
    require(saved == reconstructed, "ACTIVATION_SEAL_REPLAY_MISMATCH")
    return saved
