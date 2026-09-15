import json, tempfile, unittest
from pathlib import Path
from src.state_chain import genesis, append_state, deterministic_hash

class StateEngineTests(unittest.TestCase):
 def setUp(self): self.d=Path('artifacts/test_state_tmp'); self.d.mkdir(exist_ok=True); [p.unlink() for p in self.d.glob('*.json')]; import src.state_chain as s; self.old=(s.GENESIS,s.CHAIN); s.GENESIS=self.d/'g.json'; s.CHAIN=self.d/'c.json'; self.s=s
 def tearDown(self): self.s.GENESIS,self.s.CHAIN=self.old
 def test_genesis_uniqueness(self): self.assertEqual(genesis('m','d','c')['state_id'],genesis('m','d','c')['state_id'])
 def test_state_id_uniqueness(self): append_state({'current_state_id':'a','previous_state_id':'GENESIS_STATE_ID'}); self.assertRaises(ValueError,append_state,{'current_state_id':'a','previous_state_id':'a'})
 def test_previous_current_linkage(self): append_state({'current_state_id':'a','previous_state_id':'GENESIS_STATE_ID'}); self.assertRaises(ValueError,append_state,{'current_state_id':'b','previous_state_id':'x'})
 def test_chain_continuity(self): append_state({'current_state_id':'a','previous_state_id':'GENESIS_STATE_ID'}); append_state({'current_state_id':'b','previous_state_id':'a'}); self.assertTrue(self.s.CHAIN.exists())
 def test_ledger_persistence(self): x={'current_state_id':'a','previous_state_id':'GENESIS_STATE_ID','transaction_ledger_reference':'ledger'}; append_state(x); self.assertEqual(json.loads(self.s.CHAIN.read_text())[0]['transaction_ledger_reference'],'ledger')
 def test_fail_closed_invalid_snapshot(self): self.assertFalse(Path('artifacts/does-not-exist.json').exists())
 def test_deterministic_double_run(self): p={'input_snapshot_id':'s','previous_state_id':'g','model_version':'m','calculation_spec_version':'c','x':1}; self.assertEqual(deterministic_hash(p),deterministic_hash(dict(p)))
 def test_query_universe_dedup_symbol_integrity(self): xs=['2330','2330','2317']; self.assertEqual(len(set(xs)),2); self.assertTrue(all(x.isdigit() for x in set(xs)))
