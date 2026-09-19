import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from scripts.build_live_source_bundle import _load_persistent_stage_state


class StageBootstrapStateTests(unittest.TestCase):
    def test_missing_chain_selects_one_time_reconstruction_without_writing_genesis(self):
        path=Path(__file__).parent/f'.stage-chain-{uuid4().hex}.json'
        try:
            with patch.dict(os.environ,{'RATE_DECISION_STATE_CHAIN':str(path)}):
                self.assertIsNone(_load_persistent_stage_state())
            self.assertFalse(path.exists())
        finally:
            path.unlink(missing_ok=True)

    def test_persisted_30_symbol_stage_state_is_loaded_and_incomplete_fails_closed(self):
        symbols={str(i):{'stage_current':'CONSOLIDATION','M7_score':50,'MHE_score':50,'Rotation_score':50,'Rotation_class':'FLAT'} for i in range(30)}
        path=Path(__file__).parent/f'.stage-chain-{uuid4().hex}.json'
        try:
            path.write_text(json.dumps([{'current_state_id':'state-1','stage_state_schema_version':'RATE-PERSISTED-STAGE-V1','symbols':symbols}]),encoding='utf-8')
            with patch.dict(os.environ,{'RATE_DECISION_STATE_CHAIN':str(path)}):
                self.assertEqual(_load_persistent_stage_state()['state_id'],'state-1')
                path.write_text(json.dumps([{'current_state_id':'state-2','stage_state_schema_version':'RATE-PERSISTED-STAGE-V1','symbols':{'2330':symbols['0']}}]),encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError,'PERSISTED_STAGE_STATE_INCOMPLETE'):
                    _load_persistent_stage_state()
        finally:
            path.unlink(missing_ok=True)


if __name__=='__main__': unittest.main()
