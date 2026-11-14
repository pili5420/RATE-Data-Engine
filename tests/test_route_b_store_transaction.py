"""Synthetic, disposable crash and integrity tests for the Store commit pointer."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.route_b_store_transaction import (
    FILES, POINTER, TRANSACTIONS, StoreTransactionError,
    load_committed_store, publish_store,
)


def files(version: int) -> dict:
    return {name:{"synthetic_version":version,"name":name} for name in FILES}


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)

    def test_complete_commit_and_replay_predecessor(self):
        self.assertIsNone(load_committed_store(self.root))
        first=publish_store(self.root,files(1),expected_transaction_id=None)
        self.assertEqual(load_committed_store(self.root)["files"],files(1))
        second=publish_store(self.root,files(2),expected_transaction_id=first)
        self.assertNotEqual(first,second)
        self.assertEqual(load_committed_store(self.root)["files"],files(2))
        with self.assertRaisesRegex(StoreTransactionError,"STALE_PREDECESSOR"):
            publish_store(self.root,files(3),expected_transaction_id=first)
        self.assertEqual(load_committed_store(self.root)["transaction_id"],second)

    def test_partial_stage_failure_preserves_old_commit(self):
        old=publish_store(self.root,files(1),expected_transaction_id=None)
        from src import route_b_store_transaction as module
        real=module._write_sync
        calls=0
        def fail_second(path,data):
            nonlocal calls
            calls+=1
            if calls==2:
                raise OSError("SYNTHETIC_PARTIAL_WRITE")
            return real(path,data)
        with patch.object(module,"_write_sync",side_effect=fail_second):
            with self.assertRaisesRegex(OSError,"SYNTHETIC_PARTIAL_WRITE"):
                publish_store(self.root,files(2),expected_transaction_id=old)
        self.assertEqual(load_committed_store(self.root)["transaction_id"],old)
        self.assertFalse((self.root/".store.lock").exists())

    def test_commit_pointer_crash_preserves_old_commit(self):
        old=publish_store(self.root,files(1),expected_transaction_id=None)
        from src import route_b_store_transaction as module
        real=module.os.replace
        def fail_pointer(src,dst):
            if Path(dst).name==POINTER:
                raise OSError("SYNTHETIC_POINTER_CRASH")
            return real(src,dst)
        with patch.object(module.os,"replace",side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError,"SYNTHETIC_POINTER_CRASH"):
                publish_store(self.root,files(2),expected_transaction_id=old)
        self.assertEqual(load_committed_store(self.root)["transaction_id"],old)
        with self.assertRaises(FileExistsError):
            publish_store(self.root,files(2),expected_transaction_id=old)

    def test_tamper_missing_file_and_manifest_rejected(self):
        tx=publish_store(self.root,files(1),expected_transaction_id=None)
        target=self.root/TRANSACTIONS/tx/FILES[0]
        target.write_text(json.dumps({"forged":True}),encoding="utf-8")
        with self.assertRaisesRegex(StoreTransactionError,"FILE_HASH_INVALID"):
            load_committed_store(self.root)

    def test_uncommitted_legacy_and_lock_rejected(self):
        (self.root/FILES[0]).write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(StoreTransactionError,"UNCOMMITTED_OR_LEGACY_FILES"):
            load_committed_store(self.root)
        (self.root/FILES[0]).unlink()
        (self.root/".store.lock").write_text("synthetic",encoding="utf-8")
        with self.assertRaisesRegex(StoreTransactionError,"UNCOMMITTED_OR_LEGACY_FILES"):
            load_committed_store(self.root)
        with self.assertRaisesRegex(StoreTransactionError,"LOCK_CONFLICT"):
            publish_store(self.root,files(1),expected_transaction_id=None)


if __name__=="__main__":
    unittest.main()
