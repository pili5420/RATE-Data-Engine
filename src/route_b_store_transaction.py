"""Failure-atomic, hash-checked Route B Store snapshots.

Only CURRENT_TRANSACTION.json commits a complete four-file transaction. A stale
lock or orphan staging directory needs manual review; writers never retry it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

POINTER="CURRENT_TRANSACTION.json"
TRANSACTIONS=".transactions"
FILES=(
    "RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION.json",
    "RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE.json",
    "RATE_V11_PRODUCTION_ACCEPTANCE_SESSION.json",
    "RATE_V11_PRODUCTION_ACCEPTANCE_SESSION_SUMMARY.json",
)


class StoreTransactionError(RuntimeError):
    pass


def require(ok,reason):
    if not ok:
        raise StoreTransactionError(reason)


def _bytes(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    try:
        value=json.loads(path.read_bytes())
    except (OSError,ValueError) as exc:
        raise StoreTransactionError("STORE_TRANSACTION_READ_INVALID:"+path.name) from exc
    require(isinstance(value,dict),"STORE_TRANSACTION_OBJECT_REQUIRED:"+path.name)
    return value


def _write_sync(path,data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _validate_transaction(directory,expected_tx,expected_manifest_hash):
    require(directory.is_dir() and not directory.is_symlink(),"STORE_TRANSACTION_DIRECTORY_MISSING")
    require({p.name for p in directory.iterdir()}==set(FILES)|{"MANIFEST.json"},
            "STORE_TRANSACTION_FILE_SET_INVALID")
    require(all((directory/name).is_file() and not (directory/name).is_symlink()
                for name in (*FILES,"MANIFEST.json")),"STORE_TRANSACTION_NONREGULAR_FILE")
    manifest_bytes=(directory/"MANIFEST.json").read_bytes()
    require(_sha(manifest_bytes)==expected_manifest_hash,"STORE_TRANSACTION_MANIFEST_HASH_INVALID")
    manifest=_read(directory/"MANIFEST.json")
    require(manifest.get("artifact")=="RATE_ROUTE_B_STORE_TRANSACTION_V1"
            and manifest.get("transaction_id")==expected_tx
            and isinstance(manifest.get("files"),dict)
            and set(manifest["files"])==set(FILES),"STORE_TRANSACTION_MANIFEST_INVALID")
    content={}
    for name in FILES:
        raw=(directory/name).read_bytes()
        entry=manifest["files"][name]
        require(isinstance(entry,dict) and entry.get("sha256")==_sha(raw)
                and entry.get("bytes")==len(raw),"STORE_TRANSACTION_FILE_HASH_INVALID:"+name)
        content[name]=_read(directory/name)
    expected=_sha(_bytes({name:manifest["files"][name]["sha256"] for name in FILES}))
    require(expected==expected_tx,"STORE_TRANSACTION_ID_INVALID")
    return content


def load_committed_store(root,*,_ignore_own_lock=False):
    root=Path(root)
    pointer_path=root/POINTER
    require(not pointer_path.is_symlink(),"STORE_TRANSACTION_POINTER_SYMLINK")
    if not pointer_path.is_file():
        require(not any((root/name).exists() for name in FILES)
                and not (root/TRANSACTIONS).exists()
                and not (root/(POINTER+".tmp")).exists()
                and (_ignore_own_lock or not (root/".store.lock").exists()),
                "STORE_TRANSACTION_UNCOMMITTED_OR_LEGACY_FILES")
        return None
    pointer=_read(pointer_path)
    require(pointer.get("artifact")=="RATE_ROUTE_B_STORE_POINTER_V1"
            and set(pointer)=={"artifact","transaction_id","manifest_sha256"},
            "STORE_TRANSACTION_POINTER_INVALID")
    tx=pointer["transaction_id"]
    digest=pointer["manifest_sha256"]
    require(isinstance(tx,str) and len(tx)==64 and all(c in "0123456789abcdef" for c in tx)
            and isinstance(digest,str) and len(digest)==64,
            "STORE_TRANSACTION_POINTER_BINDING_INVALID")
    content=_validate_transaction(root/TRANSACTIONS/tx,tx,digest)
    return {"transaction_id":tx,"files":content}


def publish_store(root,files,*,expected_transaction_id):
    """Stage and verify all files, then replace one commit pointer atomically."""
    root=Path(root)
    require(set(files)==set(FILES),"STORE_TRANSACTION_INPUT_FILE_SET_INVALID")
    root.mkdir(parents=True,exist_ok=True)
    lock=root/".store.lock"
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc:
        raise StoreTransactionError("STORE_TRANSACTION_LOCK_CONFLICT") from exc
    stage=None
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(b"STORE_TRANSACTION_IN_PROGRESS\n")
            stream.flush(); os.fsync(stream.fileno())
        old=load_committed_store(root,_ignore_own_lock=True)
        actual=None if old is None else old["transaction_id"]
        require(actual==expected_transaction_id,"STORE_TRANSACTION_STALE_PREDECESSOR")
        txdir=root/TRANSACTIONS
        txdir.mkdir(exist_ok=True)
        payload={name:_bytes(files[name]) for name in FILES}
        hashes={name:_sha(payload[name]) for name in FILES}
        tx=_sha(_bytes(hashes))
        manifest={"artifact":"RATE_ROUTE_B_STORE_TRANSACTION_V1",
                  "transaction_id":tx,
                  "files":{name:{"sha256":hashes[name],"bytes":len(payload[name])}
                           for name in FILES}}
        manifest_data=_bytes(manifest)
        manifest_sha=_sha(manifest_data)
        stage=Path(tempfile.mkdtemp(prefix=".staging-",dir=txdir))
        for name in FILES:
            _write_sync(stage/name,payload[name])
        _write_sync(stage/"MANIFEST.json",manifest_data)
        _validate_transaction(stage,tx,manifest_sha)
        final=txdir/tx
        if final.exists():
            _validate_transaction(final,tx,manifest_sha)
            shutil.rmtree(stage)
        else:
            os.replace(stage,final)
        stage=None
        pointer={"artifact":"RATE_ROUTE_B_STORE_POINTER_V1",
                 "transaction_id":tx,"manifest_sha256":manifest_sha}
        pointer_tmp=root/(POINTER+".tmp")
        _write_sync(pointer_tmp,_bytes(pointer))
        os.replace(pointer_tmp,root/POINTER)
        return tx
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        # If the process is killed, the lock survives and the next writer fails closed.
        lock.unlink(missing_ok=True)
