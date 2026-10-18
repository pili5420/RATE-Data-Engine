import ast,copy,hashlib,io,json,os,sys,time,types,unittest,urllib.error
from pathlib import Path
import http_evidence as http,file_evidence as file,runner_proof as proof,model,probe,job
S=Path(__file__).resolve().parent;ENGINEERING_OUTPUT_ROOT=None
class Response:
 def __init__(self,url,status=200,body=b'{}'):self.url=url;self.status=status;self.body=body
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def getcode(self):return self.status
 def read(self,n):return self.body[:n]
class Opener:
 def __init__(self,result):self.result=result;self.calls=[]
 def open(self,req,timeout):
  self.calls.append((req.full_url,timeout))
  if isinstance(self.result,Exception):raise self.result
  return self.result
class Tests(unittest.TestCase):
 def url(self):return 'https://api.github.com/repos/'+proof.REPO+'/actions/runs/123'
 def transport(self,result):
  rows=[];op=Opener(result);t=http.Transport('a'*40,'123',lambda *r:rows.append(r),op);return t,rows,op
 def fetch(self,result):
  t,rows,op=self.transport(result)
  try:t.fetch('RUN_RECORD',self.url(),{'Authorization':'SYNTHETIC_SECRET_TOKEN'})
  except Exception:pass
  return t,rows,op
 def stat(self,**extra):
  values=dict(st_dev=11,st_ino=22,st_size=3,st_mtime_ns=44,st_ctime_ns=55,st_birthtime_ns=66,st_mode=0,st_file_attributes=0,st_reparse_tag=0,st_atime_ns=77);values.update(extra);return types.SimpleNamespace(**values)
 def image(self):
  p=ENGINEERING_OUTPUT_ROOT/(self._testMethodName+'.bin');p.write_bytes(b'abc');return p
 def test_http_200_records_fixed_stage(self):
  t,rows,op=self.fetch(Response(self.url()));self.assertEqual(t.records[0]['http_status'],200);self.assertEqual(len(op.calls),1);self.assertEqual(t.records[0]['outcome'],'RESPONSE_PARSED_NOT_AUTHORIZATION')
 def test_http_403_no_error_body_or_exception_text(self):
  error=urllib.error.HTTPError(self.url()+'?SECRET_QUERY',403,'SECRET_MESSAGE',{'Authorization':'SECRET_HEADER'},io.BytesIO(b'SECRET_BODY'));t,rows,op=self.fetch(error)
  self.assertEqual(t.records[0]['http_status'],403);self.assertNotIn('SECRET',json.dumps(rows));self.assertEqual(len(op.calls),1);self.assertEqual(error.fp.tell(),0)
 def test_http_error_401(self):self.assertEqual(self.fetch(urllib.error.HTTPError(self.url(),401,'SECRET',{},None))[0].records[0]['http_status'],401)
 def test_http_error_429(self):self.assertEqual(self.fetch(urllib.error.HTTPError(self.url(),429,'SECRET',{},None))[0].records[0]['http_status'],429)
 def test_http_error_500(self):self.assertEqual(self.fetch(urllib.error.HTTPError(self.url(),500,'SECRET',{},None))[0].records[0]['http_status'],500)
 def test_http_unsafe_status_not_exported(self):
  t,rows,op=self.fetch(Response(self.url(),'SECRET_STATUS'));self.assertIsNone(t.records[0]['http_status']);self.assertNotIn('SECRET',json.dumps(rows))
 def test_http_boolean_status_reject(self):self.assertIsNone(self.fetch(Response(self.url(),True))[0].records[0]['http_status'])
 def test_http_error_unsafe_code_not_exported(self):
  t,rows,op=self.fetch(urllib.error.HTTPError(self.url(),'SECRET_CODE','SECRET',{},None));self.assertIsNone(t.records[0]['http_status']);self.assertNotIn('SECRET',json.dumps(rows))
 def test_http_timeout_receipt(self):self.assertEqual(self.fetch(TimeoutError('SECRET'))[0].records[0]['nonsecret_error_code'],'REQUEST_TIMEOUT')
 def test_http_urlerror_receipt_no_reason(self):
  t,rows,op=self.fetch(urllib.error.URLError('SECRET_REASON'));self.assertEqual(t.records[0]['error_type'],'URLError');self.assertNotIn('SECRET',json.dumps(rows))
 def test_http_unexpected_error_sanitized(self):
  t,rows,op=self.fetch(RuntimeError('SECRET'));self.assertEqual(t.records[0]['error_type'],'UnexpectedError');self.assertNotIn('SECRET',json.dumps(rows))
 def test_http_duplicate_json_reject(self):self.assertEqual(self.fetch(Response(self.url(),body=b'{"a":1,"a":2}'))[0].records[0]['outcome'],'HALT')
 def test_http_invalid_utf8_reject(self):self.assertEqual(self.fetch(Response(self.url(),body=b'\xff'))[0].records[0]['outcome'],'HALT')
 def test_http_nonfinite_json_reject(self):self.assertEqual(self.fetch(Response(self.url(),body=b'{"a":NaN}'))[0].records[0]['outcome'],'HALT')
 def test_http_redirect_result_reject(self):self.assertEqual(self.fetch(Response('https://evil.invalid/SECRET'))[0].records[0]['outcome'],'HALT')
 def test_http_redirect_handler_raises_without_follow(self):
  with self.assertRaises(proof.Refused):http.NoRedirect().redirect_request(None,None,None,None,None,None)
 def test_http_bound_reject_no_retry(self):
  t,rows,op=self.transport(Response(self.url(),body=b'xxx'))
  with self.assertRaises(proof.Refused):t.fetch('RUN_RECORD',self.url(),bound=2)
  with self.assertRaises(proof.Refused):t.fetch('RUN_RECORD',self.url(),bound=2)
  self.assertEqual(len(op.calls),1)
 def test_http_success_cannot_be_repeated(self):
  t,rows,op=self.transport(Response(self.url()));t.fetch('RUN_RECORD',self.url())
  with self.assertRaises(proof.Refused):t.fetch('RUN_RECORD',self.url())
  self.assertEqual(len(op.calls),1)
 def test_http_failed_cannot_be_repeated(self):
  t,rows,op=self.transport(TimeoutError('SECRET'))
  with self.assertRaises(TimeoutError):t.fetch('RUN_RECORD',self.url())
  with self.assertRaises(proof.Refused):t.fetch('RUN_RECORD',self.url())
  self.assertEqual(len(op.calls),1)
 def test_http_wrong_endpoint_no_request(self):
  t,rows,op=self.transport(None)
  with self.assertRaises(proof.Refused):t.fetch('RUN_RECORD','https://evil.invalid/SECRET')
  self.assertEqual(op.calls,[]);self.assertEqual(rows,[])
 def test_http_wrong_stage_no_request(self):
  t,rows,op=self.transport(None)
  with self.assertRaises(proof.Refused):t.fetch('SECRET_STAGE',self.url())
  self.assertEqual(op.calls,[])
 def test_http_extra_query_reject(self):
  t,rows,op=self.transport(None)
  with self.assertRaises(proof.Refused):t.fetch('RUN_RECORD',self.url()+'?SECRET')
  self.assertEqual(op.calls,[])
 def test_http_credentials_in_url_reject(self):
  t,rows,op=self.transport(None)
  with self.assertRaises(proof.Refused):t.fetch('RUN_RECORD','https://SECRET@api.github.com/')
  self.assertEqual(op.calls,[])
 def test_oidc_raw_url_query_and_header_not_in_receipt(self):
  url='https://vstoken.actions.githubusercontent.com/SECRET_PATH?token=SECRET_QUERY';t,rows,op=self.transport(urllib.error.HTTPError(url,403,'SECRET',{},None))
  with self.assertRaises(urllib.error.HTTPError):t.fetch('OIDC_TOKEN',url,{'Authorization':'SECRET_AUTH'})
  self.assertNotIn('SECRET',json.dumps(rows));self.assertEqual(t.records[0]['fixed_path_id'],'GITHUB_ACTIONS_OIDC_REQUEST_PATH_NOT_EXPORTED')
 def test_oidc_host_suffix_attack_reject(self):
  t,rows,op=self.transport(None)
  with self.assertRaises(proof.Refused):t.fetch('OIDC_TOKEN','https://actions.githubusercontent.com.evil.invalid/')
  self.assertEqual(op.calls,[])
 def test_receipt_is_not_authorization(self):
  t,rows,op=self.fetch(TimeoutError('SECRET'));r=http.receipt('a'*40,'qualification','123',t.records,False,True);self.assertFalse(r['receipt_is_execution_authorization']);self.assertFalse(r['authentication_completed']);self.assertNotIn('SECRET',json.dumps(r))
 def test_receipt_extra_key_injection_reject(self):
  t,rows,op=self.fetch(TimeoutError());t.records[0]['token']='SECRET'
  with self.assertRaises(proof.Refused):http.receipt('a'*40,'qualification','123',t.records,False,True)
 def test_receipt_status_injection_reject(self):
  t,rows,op=self.fetch(TimeoutError());t.records[0]['http_status']='SECRET'
  with self.assertRaises(proof.Refused):http.receipt('a'*40,'qualification','123',t.records,False,True)
 def test_receipt_error_text_injection_reject(self):
  t,rows,op=self.fetch(TimeoutError());t.records[0]['nonsecret_error_code']='SECRET'
  with self.assertRaises(proof.Refused):http.receipt('a'*40,'qualification','123',t.records,False,True)
 def test_receipt_duplicate_stage_reject(self):
  t,rows,op=self.fetch(TimeoutError())
  with self.assertRaises(proof.Refused):http.receipt('a'*40,'qualification','123',t.records*2,False,True)
 def test_receipt_wrong_role_reject(self):
  with self.assertRaises(proof.Refused):http.receipt('a'*40,'SECRET','123',[],False,True)
 def test_file_original_five_fields_unchanged(self):self.assertEqual(file.IDENTITY_FIELDS,('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns'))
 def test_file_birthtime_separate_from_ctime(self):
  m=file.metadata(self.stat());self.assertEqual(m['st_ctime_ns'],55);self.assertEqual(m['st_birthtime_ns'],66)
 def test_file_metadata_bool_reject(self):
  with self.assertRaises(model.Unknown):file.metadata(self.stat(st_ino=True))
 def test_file_metadata_float_time_reject(self):
  with self.assertRaises(model.Unknown):file.metadata(self.stat(st_ctime_ns=1.0))
 def test_file_differences_exact_per_pair(self):
  a=file.metadata(self.stat());b=dict(a,st_dev=12);c=dict(a,st_ino=23);d=file.differences(a,b,c)
  self.assertEqual(d,{'before_vs_after':['st_dev'],'before_vs_path':['st_ino'],'after_vs_path':['st_dev','st_ino']})
 def test_file_stable_self_created_fixture(self):
  rows=[];p=self.image();r=file.disk_image(str(p),time.monotonic()+5,lambda a:True,lambda *a:rows.append(a));self.assertEqual(r['sha256'],hashlib.sha256(b'abc').hexdigest());self.assertFalse(r['loaded_image_attestation']);self.assertTrue(rows[-1][1]['equal']);self.assertEqual(len([r for r in rows if r[0]=='IMAGE_IDENTITY_QUERY']),3)
 def patched_fstat(self,change):
  p=self.image();rows=[];actual=file.os.fstat;n=[0]
  def fake(fd):
   q=actual(fd);v={k:getattr(q,k) for k in (*file.IDENTITY_FIELDS,*file.EXTRA_FIELDS) if hasattr(q,k)};n[0]+=1
   if n[0]==2:v[change]+=1
   return types.SimpleNamespace(**v)
  file.os.fstat=fake
  try:
   with self.assertRaisesRegex(model.Unknown,'IMAGE_DISK_IDENTITY_CHANGED'):file.disk_image(str(p),time.monotonic()+5,lambda a:True,lambda *a:rows.append(a))
  finally:file.os.fstat=actual
  comparison=rows[-1][1];self.assertIn(change,comparison['mismatch_fields']['before_vs_after']);self.assertFalse(comparison['equal']);self.assertFalse(comparison['loaded_image_attestation'])
 def test_file_dev_mismatch_evidence_then_halt(self):self.patched_fstat('st_dev')
 def test_file_ino_mismatch_evidence_then_halt(self):self.patched_fstat('st_ino')
 def test_file_size_mismatch_evidence_then_halt(self):self.patched_fstat('st_size')
 def test_file_mtime_mismatch_evidence_then_halt(self):self.patched_fstat('st_mtime_ns')
 def test_file_ctime_mismatch_evidence_then_halt(self):self.patched_fstat('st_ctime_ns')
 def test_file_fstat_error_record_no_message(self):
  p=self.image();rows=[];actual=file.os.fstat
  def fail(fd):raise OSError(5,'SECRET_PATH_TOKEN')
  file.os.fstat=fail
  try:
   with self.assertRaises(OSError):file.disk_image(str(p),time.monotonic()+5,lambda a:True,lambda *a:rows.append(a))
  finally:file.os.fstat=actual
  self.assertEqual(rows[-1][1]['status'],'UNKNOWN');self.assertEqual(rows[-1][1]['errno'],5);self.assertNotIn('SECRET',json.dumps(rows))
 def test_file_no_sink_cannot_proceed(self):
  with self.assertRaisesRegex(model.Unknown,'DURABLE'):file.disk_image(str(self.image()),time.monotonic()+5,lambda a:True)
 def test_file_remote_reject_before_access(self):
  with self.assertRaisesRegex(model.Unknown,'LOCAL_PHYSICAL'):file.disk_image('\\\\host\\share\\a',time.monotonic()+5,lambda a:True,lambda *a:None)
 def test_file_nonfixed_reject_before_file_read(self):
  with self.assertRaisesRegex(model.Unknown,'NOT_FIXED'):file.disk_image(str(self.image()),time.monotonic()+5,lambda a:False,lambda *a:None)
 def test_file_deadline_not_relaxed(self):
  rows=[]
  with self.assertRaisesRegex(model.Unknown,'DEADLINE'):file.disk_image(str(self.image()),time.monotonic()-1,lambda a:True,lambda *a:rows.append(a))
  self.assertFalse(any(row[0]=='IMAGE_IDENTITY_COMPARISON' for row in rows))
 def test_unsigned_constructor_still_before_native(self):
  with self.assertRaises(Exception):probe.Probe('NO_SIGNATURE',{},lambda *a:None,time.monotonic()+1)
 def test_only_exact_normal_worker_command(self):
  self.assertEqual(job.checked_command([sys.executable,'-I','-B','-S',str(S/'normal_worker.py')],{}),'normal')
  for extra in ('crash','hang','descendant_hang'):
   with self.assertRaises(job.ContainmentError):job.checked_command([sys.executable,'-I','-B','-S',str(S/'normal_worker.py'),extra],{})
 def test_no_new_enumeration_or_pid_kill_API(self):
  for name in ('controller.py','probe.py','file_evidence.py','http_evidence.py','normal_worker.py'):
   text=(S/name).read_text()
   for forbidden in ('CreateToolhelp32Snapshot','EnumProcesses','TerminateProcess','os.kill','Get-CimInstance','OpenBaseKey','AdjustTokenPrivileges','ReadProcessMemory','Popen('):self.assertNotIn(forbidden,text)
 def test_probe_open_rights_unchanged(self):self.assertIn('OpenProcess(0x101000,False,pid)',(S/'probe.py').read_text())
 def test_controller_native_after_authenticate_and_receipt(self):
  text=(S/'controller.py').read_text();self.assertLess(text.index('token,claims,actual_role'),text.index("native=loader.load('probe')"));self.assertIn("runner=Path(r'D:\\a\\_temp')",text);self.assertIn("open('xb')",text)
 def test_native_manifest_gate_still_684_base_blobs(self):
  text=(S/'controller.py').read_text();self.assertIn('len(pt)==684',text);self.assertIn("oid==ct[name]['sha']",text);self.assertIn('STACKED_BASE_MOVED_HALT',text)
 def test_old_nonce_profile_not_accepted(self):
  text=(S/'runner_proof.py').read_text();self.assertIn("AUD='rate-pf002-c03-job-member-forensics'",text);self.assertIn('codex/pf002-c03-forensic-evidence-v1',text)
 def test_no_runtime_promotion_in_model(self):
  text=(S/'model.py').read_text();self.assertIn("'RS02':'BLOCKED'",text);self.assertIn("'historical_C01_root_cause':'UNPROVEN'",text);self.assertIn("'trusted_member_allowlist_modified':False",text)
 def test_error_numbers_drop_secret_values(self):
  for value in ('SECRET',True,1.5,2**100):self.assertIsNone(file.error_number(value))
  self.assertEqual(file.error_number(5),5)
 def test_receipt_invalid_status_bounds_reject(self):
  t,rows,op=self.fetch(TimeoutError());t.records[0]['http_status']=700
  with self.assertRaises(proof.Refused):http.receipt('a'*40,'qualification','123',t.records,False,True)
 def test_receipt_success_cannot_carry_halt_error(self):
  t,rows,op=self.fetch(Response(self.url()));t.records[0]['error_type']='HTTPError';t.records[0]['nonsecret_error_code']='HTTP_STATUS_ERROR'
  with self.assertRaises(proof.Refused):http.receipt('a'*40,'qualification','123',t.records,True,False)
 def controller_functions(self):
  tree=ast.parse((S/'controller.py').read_text());nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('canonical','save','Journal','run','safe_halt','safe_native_error')]
  ns=dict(json=json,os=os,hashlib=hashlib,time=time,re=__import__('re'),Path=Path,proof=proof,model=model)
  exec(compile(ast.Module(body=nodes,type_ignores=[]),'controller.py:offline-selected-functions','exec'),ns)
  return ns
 def test_preauth_failure_durable_receipt_without_native(self):
  ns=self.controller_functions();root=ENGINEERING_OUTPUT_ROOT/'preauth_fixture';root.mkdir();calls=[]
  ns['preauth_context']=lambda:(root,'qualification','a'*40,'123');ns['physical']=lambda p:None;ns['loader']=types.SimpleNamespace(load=lambda name:calls.append(name))
  def transport(h,r,emit):return http.Transport(h,r,emit,Opener(urllib.error.HTTPError(self.url(),403,'SECRET',{'Authorization':'SECRET'},io.BytesIO(b'SECRET'))))
  ns['http']=types.SimpleNamespace(Transport=transport,receipt=http.receipt)
  ns['authenticate']=lambda t:t.fetch('RUN_RECORD',self.url(),{'Authorization':'SECRET'})
  self.assertEqual(ns['run'](),1);self.assertEqual(calls,[])
  public=root/'PF002-C03-123-1-qualification'/'public';receipt=json.loads((public/'PREAUTH_DIAGNOSTIC_RECEIPT.json').read_bytes());self.assertEqual(receipt['requests'][0]['http_status'],403);self.assertFalse(receipt['receipt_is_execution_authorization'])
  previous=None
  for p in sorted(public.glob('[0-9]*.json')):
   raw=p.read_bytes();q=json.loads(raw);self.assertEqual(q['previous_sha256'],previous);self.assertNotIn(b'SECRET',raw);previous=hashlib.sha256(raw).hexdigest()
  self.assertEqual(json.loads((public/'FINAL_HEAD.json').read_bytes())['journal_head'],previous)
  sealed_receipt=(public/'PREAUTH_DIAGNOSTIC_RECEIPT.json').read_bytes()
  with self.assertRaisesRegex(proof.Refused,'^ONE_SHOT_ROOT_EXISTS$'):ns['run']()
  self.assertEqual((public/'PREAUTH_DIAGNOSTIC_RECEIPT.json').read_bytes(),sealed_receipt)
  self.assertEqual(calls,[])
 def test_journal_immutable_create_new(self):
  ns=self.controller_functions();root=ENGINEERING_OUTPUT_ROOT/'journal_fixture';root.mkdir();j=ns['Journal'](root,'normal','a'*40,'qualification','123');j.emit('TEST',{'status':'UNKNOWN'});raw=(root/'0001_TEST.json').read_bytes();j.seq=0;j.prev=None
  with self.assertRaises(FileExistsError):j.emit('TEST',{'status':'PASS'})
  self.assertEqual((root/'0001_TEST.json').read_bytes(),raw)
 def test_halt_error_message_not_exfiltrated(self):
  ns=self.controller_functions()
  self.assertEqual(ns['safe_halt'](model.Unknown('SECRET')), 'UNEXPECTED_OPERATION_UNKNOWN')
  self.assertEqual(ns['safe_halt'](model.Unknown('IMAGE_DISK_IDENTITY_CHANGED')), 'IMAGE_DISK_IDENTITY_CHANGED')
 def test_native_halt_error_attribute_not_exfiltrated(self):
  ns=self.controller_functions();exc=OSError('SECRET');exc.winerror='SECRET_VALUE';self.assertIsNone(ns['safe_native_error'](exc));exc.winerror=5;self.assertEqual(ns['safe_native_error'](exc),5)
 def test_no_environment_or_registry_proxy_discovery(self):
  actual=http.urllib.request.getproxies
  def forbidden():raise AssertionError('SYSTEM_PROXY_DISCOVERY_FORBIDDEN')
  http.urllib.request.getproxies=forbidden
  try:t=http.Transport('a'*40,'123',lambda *a:None)
  finally:http.urllib.request.getproxies=actual
  self.assertFalse(any(getattr(h,'proxies',None) for h in t.opener.handlers))
