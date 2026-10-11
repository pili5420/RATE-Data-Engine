"""Immutable publication objects and one authoritative, OS-locked CAS pointer."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

KIND = "RATE_PRODUCTION_REFRESH_MANIFEST_V1"
LATEST = "RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json"
FILES = {"source_bundle": "RATE_PRODUCTION_SOURCE_BUNDLE.json",
         "source_snapshot": "RATE_PRODUCTION_SOURCE_BUNDLE_SNAPSHOT.json",
         "thin_work_manifest": "RATE_THIN_WORK_PRODUCTION_BUNDLE_MANIFEST_V1.json"}
OBJECT_FILES = {**FILES, "refresh_manifest": "RATE_PRODUCTION_REFRESH_MANIFEST_V1.json"}


class PublicationError(ValueError):
    pass


def require(condition, reason):
    if not condition: raise PublicationError(reason)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(body):
    return hashlib.sha256(body).hexdigest()


def decode(body):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "REFRESH_DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def number(value):
        result = float(value)
        require(math.isfinite(result), "REFRESH_NONFINITE_JSON")
        return result
    def constant(value): raise PublicationError("REFRESH_NONFINITE_JSON")
    return json.loads(body, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)


def safe(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)),
            "REFRESH_LINK_PATH_FORBIDDEN")
    return path


def sync_directory(path):
    # Windows fsyncs file handles; os.replace is same-volume atomic. No power-loss claim.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def put_object(root, role, value):
    require(role in OBJECT_FILES, "REFRESH_ARTIFACT_ROLE_INVALID")
    root = safe(root); body = encode(value); identity = digest(body)
    path = safe(root / "production_source_snapshots" / "objects" / identity / OBJECT_FILES[role])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        require(path.read_bytes() == body, "REFRESH_IMMUTABLE_OBJECT_CONFLICT")
        with path.open("r+b") as stream: os.fsync(stream.fileno())
    require(path.read_bytes() == body, "REFRESH_STAGING_VERIFICATION_FAILED")
    for directory in (path.parent, path.parent.parent, path.parent.parent.parent, root): sync_directory(directory)
    return {"path": path.relative_to(root).as_posix(), "sha256": identity, "bytes": len(body)}


def object_at(root, role, reference):
    require(role in OBJECT_FILES and isinstance(reference, dict), "REFRESH_ARTIFACT_ROLE_INVALID")
    identity = reference.get("sha256")
    require(isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{64}", identity), "REFRESH_ARTIFACT_HASH_INVALID")
    expected = Path("production_source_snapshots") / "objects" / identity / OBJECT_FILES[role]
    require(reference.get("path") == expected.as_posix(), "REFRESH_ARTIFACT_PATH_INVALID")
    path = safe(Path(root) / expected)
    require(path.is_file(), "REFRESH_REQUIRED_ARTIFACT_MISSING")
    body = path.read_bytes()
    require(digest(body) == identity and len(body) == reference.get("bytes"), "REFRESH_ARTIFACT_TAMPER")
    return decode(body)


def manifest_digest(value):
    return digest(encode({k: v for k, v in value.items() if k != "refresh_manifest_sha256"}))


def verify_manifest(root, manifest):
    require(manifest.get("artifact_kind") == KIND and manifest.get("authoritative_commit_points") == 1
            and manifest.get("refresh_manifest_sha256") == manifest_digest(manifest), "REFRESH_MANIFEST_TAMPER")
    require(manifest.get("validation_status") == "PASS" and manifest.get("transaction_status") == "COMMITTED",
            "REFRESH_MANIFEST_NOT_COMMITTED")
    stamp = datetime.fromisoformat(manifest["commit_timestamp"].replace("Z", "+00:00"))
    require(stamp.tzinfo is not None and stamp <= datetime.now(timezone.utc), "REFRESH_COMMIT_TIME_INVALID")
    refs = manifest.get("required_artifacts", {})
    require(set(refs) == set(FILES), "REFRESH_REQUIRED_ARTIFACT_SET")
    objects = {role: object_at(root, role, refs[role]) for role in FILES}
    for field, role in (("immutable_snapshot_path", "source_snapshot"), ("immutable_bundle_path", "source_bundle")):
        require(safe(manifest[field]) == safe(Path(root) / refs[role]["path"]), "REFRESH_LEGACY_REFERENCE_INVALID")
    snapshot, bundle, thin = objects["source_snapshot"], objects["source_bundle"], objects["thin_work_manifest"]
    value_hash = digest(json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    require(snapshot["bundle"] == bundle and snapshot["source_bundle_hash"] == value_hash == manifest["source_bundle_hash"],
            "REFRESH_BUNDLE_BINDING_INVALID")
    require(snapshot["snapshot_id"] == bundle["production_snapshot_id"] == thin["production_snapshot_id"] == manifest["snapshot_id"]
            and snapshot["previous_snapshot_id"] == manifest["previous_snapshot_id"], "REFRESH_SNAPSHOT_BINDING_INVALID")
    require(manifest["input_snapshot_id"] == bundle["input_snapshot_id"] and manifest["production_snapshot_id"] == snapshot["snapshot_id"],
            "REFRESH_INPUT_BINDING_INVALID")
    require(datetime.fromisoformat(thin["generated_at"].replace("Z", "+00:00")) <= stamp, "REFRESH_COMMIT_BEFORE_STAGING")
    for field, key in (("cadence", "cadence"), ("trading_date", "market_date"), ("workflow_run_id", "run_id")):
        require(manifest[field] == snapshot[field] == thin[key], "REFRESH_SCOPE_BINDING_INVALID")
    seed = {"snapshot_sha256": refs["source_snapshot"]["sha256"], "prior_latest_identity": manifest["prior_latest_identity"]}
    require(manifest["refresh_transaction_id"] == "rate-refresh-" + digest(encode(seed)), "REFRESH_TRANSACTION_ID_INVALID")
    ref = thin["payload_references"]
    require(len(ref) == 1 and safe(ref[0]["path"]) == safe(Path(root) / refs["source_bundle"]["path"])
            and ref[0]["sha256"] == refs["source_bundle"]["sha256"], "REFRESH_THIN_REFERENCE_INVALID")
    from .thin_work_manifest import validate_shadow_manifest
    # Replay the validation at its sealed generation time, not as a new freshness claim.
    result = validate_shadow_manifest(thin, root=root, expected_run_id=manifest["workflow_run_id"],
        expected_production_snapshot_id=manifest["snapshot_id"], now=datetime.fromisoformat(thin["generated_at"].replace("Z", "+00:00")))
    require(result["validation_status"] == "PASS", "REFRESH_THIN_VALIDATION_FAILED")
    return objects


def read_committed(latest_path, expected_sha256=None):
    path = safe(latest_path); body = path.read_bytes()
    require(expected_sha256 is None or digest(body) == expected_sha256, "REFRESH_LATEST_IDENTITY_MISMATCH")
    manifest = decode(body)
    archived = {"path": "production_source_snapshots/objects/" + digest(body) + "/" + OBJECT_FILES["refresh_manifest"],
                "sha256": digest(body), "bytes": len(body)}
    require(object_at(path.parent, "refresh_manifest", archived) == manifest, "REFRESH_MANIFEST_ARCHIVE_MISMATCH")
    return {"manifest": manifest, "latest_identity": digest(body), "artifacts": verify_manifest(path.parent, manifest)}


@contextmanager
def writer_lock(root):
    root = safe(root); root.mkdir(parents=True, exist_ok=True)
    with (root / ".refresh-publication.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell(): stream.write(b"0"); stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            lock = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            lock = lambda: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(stream, fcntl.LOCK_UN)
        try: lock()
        except OSError as exc: raise PublicationError("REFRESH_WRITER_CONFLICT") from exc
        try: yield
        finally: stream.seek(0); unlock()


def current_identity(path):
    path = safe(path)
    return digest(path.read_bytes()) if path.exists() else None


def commit(root, manifest, expected_previous, write_pointer):
    root = safe(root); pointer = root / LATEST
    with writer_lock(root):
        require(current_identity(pointer) == expected_previous, "REFRESH_CAS_STALE_CURRENT")
        require(manifest["prior_latest_identity"] == expected_previous, "REFRESH_CAS_MANIFEST_PRIOR_MISMATCH")
        prior = decode(pointer.read_bytes()) if expected_previous is not None else {}
        require(manifest["previous_snapshot_id"] == prior.get("snapshot_id"), "REFRESH_PRIOR_SNAPSHOT_MISMATCH")
        put_object(root, "refresh_manifest", manifest)
        verify_manifest(root, manifest)
        # The callback performs exactly one same-directory atomic replace after file fsync.
        identity = digest(encode(manifest)); warnings = []
        try:
            write_pointer(pointer, manifest)
        except Exception as exc:
            # A post-replace error cannot undo a committed transaction.
            if current_identity(pointer) != identity: raise
            warnings.append("POST_COMMIT_WRITER_ERROR:" + type(exc).__name__)
        actual = current_identity(pointer)
        require(actual == identity, "REFRESH_COMMIT_NOT_OBSERVED" if actual == expected_previous else "REFRESH_COMMIT_OUTCOME_UNKNOWN")
    return {"latest_identity": identity, "warnings": warnings}
