"""Synthetic ACL/directory-handle contract, not a Windows security descriptor API."""
import copy
from .protocol import require,exact,uint,digest,canonical,rawhex
def check_root_proof(value,expected_root,operator_sid):
 exact(value,{'source','path','owner_sid','dacl_protected','inherited_aces','aces','reparse','volume','file_id','handle_generation','before_anchor','after_anchor'})
 require(value['source']=='SYNTHETIC_ACL_DIRECTORY_ORACLE_NOT_NATIVE','REAL_ACL_PROVENANCE_UNKNOWN','INDETERMINATE')
 require(value['path']==expected_root and value['owner_sid']==operator_sid and value['dacl_protected'] is True and type(value['inherited_aces']) is int and value['inherited_aces']==0 and value['reparse'] is False,'ROOT_OWNER_PATH_INHERITANCE_OR_REPARSE')
 require(type(value['aces']) is list and value['aces']==[{'type':'ALLOW','sid':operator_sid,'rights':'SYNTHETIC_PRIVATE_EVIDENCE_RW'}],'ACL_EFFECTIVE_ACCESS_UNPROVEN','INDETERMINATE')
 require(uint(value['volume'],64,1) and len(rawhex(value['file_id'],16))==16 and uint(value['handle_generation'],64,1),'DIRECTORY_IDENTITY')
 anchor={'volume':value['volume'],'file_id':value['file_id'],'handle_generation':value['handle_generation']}
 require(canonical(value['before_anchor'])==canonical(anchor) and canonical(value['after_anchor'])==canonical(anchor),'DIRECTORY_HANDLE_RACE_OR_REPLACEMENT','INDETERMINATE')
 return {'status':'PASS_SYNTHETIC_ROOT_CONTRACT_ONLY','anchor':anchor,'native_acl_verified':False,'power_loss_durability_verified':False}
