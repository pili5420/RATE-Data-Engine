import copy,hashlib,json,os,struct,subprocess,sys,time,unittest
from pathlib import Path
from uuid import uuid4
from .. import abi
from ..contracts import *
from ..protocol import Blocked,digest,canonical,decode
from ..engine import OfflinePreflight
from ..trust import SyntheticTrust
from ..journal import accepted_workspace
from . import fixtures as f
from . import test_preflight as core
class AbiTests(unittest.TestCase):
 def test_independent_golden_x86(self):
  l=abi.layout('win32');self.assertEqual((l['pointer'],l['DWORD'],l['FILETIME'],l['SID_AND_ATTRIBUTES'],l['TOKEN_GROUPS_OFFSET'],l['TOKEN_GROUPS_STRIDE'],l['TOKEN_MANDATORY_LABEL']),(4,4,8,8,4,8,8))
 def test_independent_golden_x64(self):
  l=abi.layout('win64');self.assertEqual((l['pointer'],l['DWORD'],l['FILETIME'],l['SID_AND_ATTRIBUTES'],l['TOKEN_GROUPS_OFFSET'],l['TOKEN_GROUPS_STRIDE'],l['TOKEN_MANDATORY_LABEL']),(8,4,8,16,8,16,16))
 def test_llp64_windows_dword_always32(self):self.assertEqual(abi.layout('win32')['DWORD'],abi.layout('win64')['DWORD']);self.assertEqual(abi.dword(0xffffffff),0xffffffff)
 def test_filetime_high_low_order(self):self.assertEqual(abi.filetime(struct.pack('<II',0x11223344,0xaabbccdd).hex()),0xaabbccdd11223344)
 def test_utf16_supplementary_code_units(self):
  text='A😀𐐷';self.assertEqual(abi.utf16((text+'\0').encode('utf-16-le').hex(),5,20),text)
 def test_utf16_empty_known_buffer(self):self.assertEqual(abi.utf16('0000',0,4,False),'')
 def test_sid_authority_big_endian_and_subauthority_little(self):self.assertEqual(abi.sid(f.sid_bytes('S-1-281474976710655-4294967295')),'S-1-281474976710655-4294967295')
 def test_sid_zero_subauthority(self):self.assertEqual(abi.sid(bytes([1,0])+bytes([0,0,0,0,0,5])),'S-1-5')
 def test_owned_buffer_read_then_release(self):
  row=f.allocation('x',b'ABCD','win64','SYNTHETIC-OWNER');a=abi.ByteArena('win64','SYNTHETIC-OWNER',[row]);self.assertEqual(a.read('x',row['base'],4,'SYNTHETIC-OWNER',1),b'ABCD');a.close()
  with self.assertRaisesRegex(Blocked,'CLOSED'):a.read('x',row['base'],1,'SYNTHETIC-OWNER',1)
  with self.assertRaisesRegex(Blocked,'DOUBLE'):a.close()
 def test_handle_borrowed_not_closed(self):
  t=abi.HandleTable('win64','SYNTHETIC-OWNER');t.register(0x4000,'desktop',1,True)
  with self.assertRaisesRegex(Blocked,'BORROWED'):t.close(0x4000,'desktop',1)
 def test_handle_owned_exactly_once(self):
  t=abi.HandleTable('win32','SYNTHETIC-OWNER');t.register(0x4000,'token',1);t.close(0x4000,'token',1)
  with self.assertRaisesRegex(Blocked,'CLOSED'):t.require(0x4000,'token',1)
  with self.assertRaisesRegex(Blocked,'REUSE'):t.register(0x4000,'token',2)
 def test_handle_wrong_kind_generation(self):
  t=abi.HandleTable('win64','SYNTHETIC-OWNER');t.register(0x4000,'token',2)
  for kind,generation in [('process',2),('token',1),('token',True)]:
   with self.assertRaises(Blocked):t.require(0x4000,kind,generation)
 def test_arena_mutation_is_not_ignored(self):
  row=f.allocation('x',b'ABCD','win64','SYNTHETIC-OWNER');a=abi.ByteArena('win64','SYNTHETIC-OWNER',[row]);a.rows['x']['data_hex']='00000000'
  with self.assertRaisesRegex(Blocked,'MUTATED'):a.read('x',row['base'],4,'SYNTHETIC-OWNER',1)

def arena_negative(abi_name,case):
 def test(self):
  row=f.allocation('x',b'ABCD','win64' if abi_name=='win64' else 'win32','SYNTHETIC-OWNER');a=abi.ByteArena(abi_name,'SYNTHETIC-OWNER',[row]);base=row['base'];args={'buffer_id':'x','pointer':base,'length':4,'owner':'SYNTHETIC-OWNER','generation':1,'alignment':1}
  if case=='underflow':args['pointer']=base-1
  elif case=='tail':args['pointer']=base+1
  elif case=='overflow':args.update(pointer=2**(abi.layout(abi_name)['pointer']*8)-1,length=4)
  elif case=='bool_pointer':args['pointer']=True
  elif case=='bool_length':args['length']=True
  elif case=='float_length':args['length']=4.0
  elif case=='alignment':args.update(pointer=base+1,length=1,alignment=4)
  elif case=='owner':args['owner']='SYNTHETIC-OTHER'
  elif case=='generation':args['generation']=2
  elif case=='bool_alignment':args['alignment']=True
  elif case=='unknown_buffer':args['buffer_id']='foreign'
  with self.assertRaises(Blocked):a.read(**args)
 return test
for arch in ['win32','win64']:
 for case in ['underflow','tail','overflow','bool_pointer','bool_length','float_length','alignment','owner','generation','bool_alignment','unknown_buffer']:setattr(AbiTests,'test_arena_'+arch+'_'+case,arena_negative(arch,case))

def sid_pointer_negative(arch,case):
 def test(self):
  owner='SYNTHETIC-OWNER';row=f.sid_allocation(2,arch,owner);data=bytearray.fromhex(row['data_hex']);l=abi.layout(arch);slot=l['TOKEN_GROUPS_OFFSET'];ptr=l['pointer']
  if case=='header_alias':data[slot:slot+ptr]=(row['base']).to_bytes(ptr,'little')
  elif case=='foreign':data[slot:slot+ptr]=(row['base']+row['capacity']+4).to_bytes(ptr,'little')
  elif case=='null':data[slot:slot+ptr]=bytes(ptr)
  elif case=='misaligned':data[slot:slot+ptr]=(row['base']+row['capacity']-1).to_bytes(ptr,'little')
  elif case=='huge_count':data[:4]=struct.pack('<I',0xffffffff)
  elif case=='sid_count':data[l['TOKEN_GROUPS_OFFSET']+l['TOKEN_GROUPS_STRIDE']+1]=16
  elif case=='sid_revision':data[l['TOKEN_GROUPS_OFFSET']+l['TOKEN_GROUPS_STRIDE']]=2
  elif case=='uninitialized_sid':row['initialized']=l['TOKEN_GROUPS_OFFSET']+l['TOKEN_GROUPS_STRIDE']
  row['data_hex']=data.hex();a=abi.ByteArena(arch,owner,[row])
  with self.assertRaises(Blocked):abi.token_groups(a,'token',1)
 return test
for arch in ['win32','win64']:
 for case in ['header_alias','foreign','null','misaligned','huge_count','sid_count','sid_revision','uninitialized_sid']:setattr(AbiTests,'test_sid_pointer_'+arch+'_'+case,sid_pointer_negative(arch,case))

def utf16_negative(raw,count,capacity):
 def test(self):
  with self.assertRaises((Blocked,UnicodeError,ValueError)):abi.utf16(raw,count,capacity)
 return test
for name,raw,count,cap in [('unpaired','00d80000',1,10),('embedded_nul','4100000042000000',3,10),('no_terminator','4100',1,10),('truncated_boundary','41000000',1,2),('bool_count','41000000',True,10),('wrong_unit_count','3dd800de0000',1,10),('odd_bytes','410000',1,10)]:setattr(AbiTests,'test_utf16_'+name,utf16_negative(raw,count,cap))
for value in [True,1.0,-1,0,2**32,2**64-1]:
 def handle_bad(self,value=value):
  with self.assertRaises(Blocked):abi.handle(value,'win32')
 setattr(AbiTests,'test_handle_win32_bad_'+str(value).replace('.','_').replace('-','neg'),handle_bad)

class ContainmentTests(unittest.TestCase):
 def fresh(self):return core.ROOT.parent/(core.ROOT.name+'-child-'+uuid4().hex)
 def run_child(self,mode,kill=False):
  root=self.fresh();root.mkdir();attempt='SYNTHETIC-'+uuid4().hex;nonce='SYNTHETIC-'+uuid4().hex;script=Path(__file__).with_name('owned_worker.py');cmd=[sys.executable,'-I','-B','-S',str(script),'--root',str(root),'--mode',mode,'--attempt',attempt,'--nonce',nonce]
  env={k:v for k,v in os.environ.items() if k in {'SystemRoot','WINDIR','TEMP','TMP','PATH'}};p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env);started=time.monotonic();killed=False
  try:
   if kill:
    while not (root/'CHILD_READY.json').exists() and p.poll() is None and time.monotonic()-started<10:time.sleep(.01)
    p.kill();killed=True
   out,err=p.communicate(timeout=15)
  finally:
   if p.poll() is None:p.kill();out,err=p.communicate(timeout=5);killed=True
  record={'pid':p.pid,'command':cmd,'exit_code':p.returncode,'parent_killed_owned_child':killed,'elapsed_seconds':time.monotonic()-started,'source_sha256':hashlib.sha256(script.read_bytes()).hexdigest()};(root/'PROCESS_RESULT.json').write_bytes(canonical(record));(root/'STDOUT.log').write_bytes(out);(root/'STDERR.log').write_bytes(err)
  if kill:self.assertTrue((root/'CHILD_READY.json').exists(),'Owned child never became ready;process and logs preserved')
  return root,attempt,nonce,p.returncode,record
 def replay_denied(self,root,nonce):
  b=f.make(root,core.KEYS);b['issuer']['payload']['nonce']=nonce;f.refresh(b,core.KEYS);r=OfflinePreflight().run(b,SyntheticTrust(core.KEYS.bundle),root);self.assertIn(r['status'],{'BLOCKED','INDETERMINATE'});self.assertFalse(r['native_execution_authorized'])
 def test_actual_owned_child_timeout_kill_unknown_no_resume(self):
  root,attempt,nonce,code,record=self.run_child('sleep',True);self.assertNotEqual(code,0);self.assertTrue(record['parent_killed_owned_child']);self.assertEqual(accepted_workspace(root).audit_attempt(attempt)['state'],'UNKNOWN_PARTIAL_OR_CRASH');self.replay_denied(root,nonce)
 def test_secret_not_inherited_by_fixed_worker(self):
  os.environ['NQ_SYNTHETIC_SECRET_SENTINEL']='SYNTHETIC-NEVER-LOG-VALUE'
  try:root,attempt,nonce,code,record=self.run_child('clean')
  finally:del os.environ['NQ_SYNTHETIC_SECRET_SENTINEL']
  self.assertEqual(code,0);ready=json.loads((root/'CHILD_READY.json').read_bytes());self.assertFalse(ready['secret_present']);self.assertEqual(ready['pid'],record['pid'])
 def test_worker_has_no_descendant_or_native_code(self):
  tree=__import__('ast').parse(Path(__file__).with_name('owned_worker.py').read_bytes())
  for n in __import__('ast').walk(tree):
   if isinstance(n,__import__('ast').Import):self.assertFalse({a.name for a in n.names}&{'subprocess','ctypes','socket'})
   if isinstance(n,__import__('ast').Call):self.assertNotIn(__import__('ast').unparse(n.func),{'os.system','os.spawnv','os.startfile','os.execv'})

def crash_child(mode):
 def test(self):
  root,attempt,nonce,code,record=self.run_child(mode);self.assertEqual(code,73);self.assertEqual(accepted_workspace(root).audit_attempt(attempt)['state'],'UNKNOWN_PARTIAL_OR_CRASH');self.replay_denied(root,nonce)
 return test
for mode in ['after_lock','after_attempt','after_claim','after_result']:setattr(ContainmentTests,'test_actual_child_crash_'+mode,crash_child(mode))
