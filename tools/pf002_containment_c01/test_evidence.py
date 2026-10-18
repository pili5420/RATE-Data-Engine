"""Synthetic receipt negatives; never native proof or live authorization."""
import copy,hashlib,json,time,unittest
from pathlib import Path
import state,runner_proof as proof,verify_evidence as verify
from test_state import Fake
S=Path(__file__).resolve().parent
ENGINEERING_OUTPUT_ROOT=None
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()+b'\n'
class Tests(unittest.TestCase):
 def fixture(self):
  root=ENGINEERING_OUTPUT_ROOT/self._testMethodName;root.mkdir();(root/'cases').mkdir();head='a'*40;rid='123';role='qualification';results=[]
  manifest=json.loads((S/'SOURCE_MANIFEST_V1.json').read_bytes())
  (root/'SOURCE_MANIFEST.json').write_bytes(canonical(manifest))
  claims={'iss':proof.ISS,'aud':proof.AUD,'repository':proof.REPO,'repository_id':'1370145728','repository_owner_id':'325481386','ref':proof.REF,'event_name':'push','runner_environment':'github-hosted','workflow_ref':proof.WORKFLOW,'sha':head,'workflow_sha':head,'run_id':rid,'run_attempt':'1'}
  provenance={'head':head,'role':role,'claims':claims,'source_manifest_sha256':hashlib.sha256((S/'SOURCE_MANIFEST_V1.json').read_bytes()).hexdigest(),'source_CIM_registry_reads':0,'original_host_queries':0,'owner_consent_issued':False,'NoAutoNext':True}
  (root/'PROVENANCE.json').write_bytes(canonical(provenance))
  for index,mode in enumerate(('normal','crash','hang','descendant_hang')):
   folder=root/'cases'/mode;folder.mkdir();counter=[0];prev=[None]
   def emit(event,data):
    counter[0]+=1;v={'sequence':counter[0],'previous_sha256':prev[0],'case':mode,'head':head,'role':role,'run_id':rid,'event':event,'utc_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),'data':copy.deepcopy(data)}
    b=canonical(v);(folder/f'{counter[0]:04d}_{event}.json').write_bytes(b);prev[0]=hashlib.sha256(b).hexdigest()
   jobname='Local\\RATE-PF002-C01-'+rid+'-'+role+'-'+str(index)*32
   emit('CASE_INTENT',{'status':'STARTED'})
   emit('JOB_CREATED',{'job_name':jobname,'job_handle':50,'active_before':0,'job_pids':[],'active_process_limit':4,'kill_on_close':True,'breakaway':False})
   emit('ROOT_CREATED_SUSPENDED_ASSIGNED_RESUMED',{'pid':11,'tid':111,'root_handle':100,'assigned_before_resume':True,'suspended_creation':True,'thread_handle_closed':True,'active_before_resume':1,'job_pids_before_resume':[11]})
   known={11};p=Fake(mode=mode)
   if mode=='descendant_hang':
    known.add(12);emit('OWNED_DESCENDANT_CONFIRMED',{'pid':12,'parent_pid':11,'same_job_confirmed':True,'retained_handle':200});old=p.snapshot
    def snap():
     v=old();v['job_pids'].append(12);v['handles'].append({'kind':'descendant','handle':200,'wait':0,'exit_code':124});return v
    p.snapshot=snap
   result=state.qualify(p,mode,3 if mode=='descendant_hang' else 2 if mode=='hang' else 10,known,emit)
   results.append({'case':mode,'root_pid':11,'descendant_pid':12 if mode=='descendant_hang' else None,'job_name':jobname,**result,'journal_head':prev[0]})
   emit('OWN_JOB_RESOURCES_CLOSED',{'job_name':jobname,'status':'CLOSED','resources':[{'kind':'job','handle':50,'closed':True,'win32_error':None}]+[{'kind':'stream','index':i,'closed':True,'win32_error':None} for i in range(3)],'not_a_termination_proof':True})
  summary={'head':head,'role':role,'cases':results,'status':'CONTAINMENT_CASES_PASS','observed_legacy_red_cases':['normal','crash'],'overall_PF002_runtime':'BLOCKED','source_CIM_registry_reads':0,'owner_consent_issued':False,'NoAutoNext':True,'original_GUI_HALT_root_cause':'UNKNOWN','handle_release_vs_elapsed_time_causal_isolation':False}
  (root/'QUALIFICATION.json').write_bytes(canonical(summary));return root
 def check(self,root):return verify.verify(root,'a'*40,'qualification','123')
 def change(self,path,mutate):v=json.loads(path.read_bytes());mutate(v);path.write_bytes(canonical(v))
 def test_complete_synthetic_chain_validation_only(self):self.assertEqual(self.check(self.fixture())['cases'],4)
 def test_source_manifest_tamper_rejected(self):
  r=self.fixture();self.change(r/'SOURCE_MANIFEST.json',lambda v:v.update(extra='injected'))
  with self.assertRaisesRegex(verify.Invalid,'MANIFEST_BINDING'):self.check(r)
 def test_old_audience_receipt_rejected(self):
  r=self.fixture();self.change(r/'PROVENANCE.json',lambda v:v['claims'].update(aud='old'))
  with self.assertRaisesRegex(verify.Invalid,'CLAIMS_CONTEXT'):self.check(r)
 def test_event_hash_tamper_rejected(self):
  r=self.fixture();self.change(r/'cases/normal/0002_JOB_CREATED.json',lambda v:v['data'].update(job_handle=999))
  with self.assertRaisesRegex(verify.Invalid,'HASH_CHAIN'):self.check(r)
 def test_missing_post_terminal_close_rejected(self):
  r=self.fixture();p=sorted((r/'cases/normal').iterdir())[-1];p.unlink()
  with self.assertRaisesRegex(verify.Invalid,'EVENT_PROTOCOL'):self.check(r)
 def test_extra_public_file_rejected(self):
  r=self.fixture();(r/'unexpected.json').write_bytes(b'{}\n')
  with self.assertRaisesRegex(verify.Invalid,'PUBLIC_ROOT_CLOSURE'):self.check(r)
 def test_false_runtime_promotion_rejected(self):
  r=self.fixture();self.change(r/'QUALIFICATION.json',lambda v:v.update(overall_PF002_runtime='PASS'))
  with self.assertRaisesRegex(verify.Invalid,'SUMMARY_BOUNDARY'):self.check(r)
 def test_duplicate_key_json_rejected(self):
  r=self.fixture();(r/'PROVENANCE.json').write_bytes(b'{"head":"a","head":"b"}\n')
  with self.assertRaisesRegex(verify.Invalid,'DUPLICATE_KEY'):self.check(r)
 def test_empty_resource_receipt_rejected(self):
  r=self.fixture();p=sorted((r/'cases/normal').iterdir())[-1];self.change(p,lambda v:v['data'].update(resources=[]))
  with self.assertRaisesRegex(verify.Invalid,'RESOURCE_CLOSE_IDENTITY'):self.check(r)
 def test_resource_handle_replacement_rejected(self):
  r=self.fixture();p=sorted((r/'cases/normal').iterdir())[-1];self.change(p,lambda v:v['data']['resources'][0].update(handle=999))
  with self.assertRaisesRegex(verify.Invalid,'RESOURCE_CLOSE_IDENTITY'):self.check(r)
 def test_auto_next_false_rejected(self):
  r=self.fixture();self.change(r/'QUALIFICATION.json',lambda v:v.update(NoAutoNext=False))
  with self.assertRaisesRegex(verify.Invalid,'SUMMARY_BOUNDARY'):self.check(r)
 def test_boolean_zero_source_count_rejected(self):
  r=self.fixture();self.change(r/'PROVENANCE.json',lambda v:v.update(source_CIM_registry_reads=False))
  with self.assertRaisesRegex(verify.Invalid,'SAFETY_BOUNDARY'):self.check(r)
