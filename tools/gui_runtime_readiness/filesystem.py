"""Self-relative security descriptor parser and private immutable test records.

The parser consumes owned synthetic bytes. File-stat/fsync tests are actual
private filesystem operations; they do not qualify native ACL/handle races or
power-loss behavior and must never be represented as such.
"""
import hashlib,os,re,stat,struct
from pathlib import Path
from gui_native_preflight.abi import sid
from gui_native_preflight.protocol import require,uint,rawhex,digest,canonical
from .contracts import blocked_runtime

OWNER_EVIDENCE_MASK=0x001201bf

def validate_descriptor(raw,expected_owner):
    data=rawhex(raw,65536);require(20<=len(data)<=65536,'SECURITY_DESCRIPTOR_LENGTH')
    revision,sbz,control,owner,group,sacl,dacl=struct.unpack('<BBHIIII',data[:20])
    require(revision==1 and sbz==0 and control==0x9004 and sacl==0 and group==0,'SELF_RELATIVE_PROTECTED_DACL_ONLY')
    require(owner>=20 and dacl>=20 and owner%4==dacl%4==0 and owner+8<=len(data) and dacl+8<=len(data),'DESCRIPTOR_OFFSET_BOUNDS')
    count=data[owner+1];size=8+4*count;require(owner==20 and dacl==owner+size and owner+size<=len(data),'OWNER_SID_BOUND_CANONICAL_LAYOUT');actual=sid(data[owner:owner+size]);require(actual==expected_owner,'OWNER_SID_MISMATCH')
    rev,pad,acl_size,ace_count,pad2=struct.unpack('<BBHHH',data[dacl:dacl+8]);require(rev==2 and pad==pad2==0 and ace_count==1 and acl_size>=16 and dacl+acl_size==len(data),'ACL_REVISION_SIZE_OR_COUNT')
    require(owner+size<=dacl or dacl+acl_size<=owner,'OWNER_DACL_OVERLAP')
    ace_type,flags,ace_size,mask=struct.unpack('<BBHI',data[dacl+8:dacl+16]);require(ace_type==0 and flags==0 and ace_size==acl_size-8 and ace_size%4==0 and mask==OWNER_EVIDENCE_MASK,'ACL_UNKNOWN_INHERITANCE_OR_EXCESS_RIGHTS')
    trustee=sid(data[dacl+16:dacl+acl_size]);require(trustee==expected_owner,'NONOWNER_ACE')
    return {'state':'OFFLINE_DESCRIPTOR_VALIDATED','owner_sid':actual,'mask':mask,'native_acl_verified':False,**blocked_runtime()}

class PrivateEvidenceStore:
    def __init__(self,root):
        p=Path(root);require(p.parent==Path(r'D:\Codex') and re.fullmatch(r'RATE-Gate2-Native-Offline-(?:Tests|Review)-[A-Za-z0-9-]+',p.name) is not None,'PRIVATE_EVIDENCE_ROOT_REQUIRED')
        self.root=p;self.anchor=self._anchor();self.failed=False
    def _anchor(self):
        s=self.root.lstat();require(stat.S_ISDIR(s.st_mode) and not self.root.is_symlink() and not s.st_file_attributes&0x400,'REPARSE_OR_NON_DIRECTORY_ROOT')
        return (s.st_dev,s.st_ino)
    def unchanged(self):require(self._anchor()==self.anchor,'ROOT_REPLACED','INDETERMINATE')
    def write_once(self,name,value):
        require(not self.failed,'FAILED_STORE_NO_RETRY');require(type(name) is str and re.fullmatch(r'SYNTHETIC-[A-Za-z0-9-]{1,100}\.json',name) is not None,'EVIDENCE_BASENAME_ONLY')
        path=self.root/name
        try:
            self.unchanged();raw=canonical(value);require(len(raw)<=4*1024*1024,'EVIDENCE_SIZE_BOUND')
            with path.open('xb') as f:
                f.write(raw);f.flush();os.fsync(f.fileno());info=os.fstat(f.fileno());require(info.st_nlink==1 and not info.st_file_attributes&0x400,'FILE_LINK_OR_REPARSE')
            self.unchanged();after=path.lstat();require((after.st_dev,after.st_ino)==(info.st_dev,info.st_ino) and after.st_nlink==1 and not after.st_file_attributes&0x400 and path.read_bytes()==raw,'EVIDENCE_REPLACED_OR_MODIFIED','INDETERMINATE')
            return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'state':'TEST_FILE_FSYNC_OBSERVED','native_acl_verified':False,'directory_handle_race_verified':False,'power_loss_durable':False,**blocked_runtime()}
        except BaseException:self.failed=True;raise

def inspect_private_file(path):
    p=Path(path);store=PrivateEvidenceStore(p.parent);store.unchanged();s=p.lstat();require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and not s.st_file_attributes&0x400 and not p.is_symlink(),'FILE_NOT_PRIVATE_REGULAR_SINGLE_LINK');return {'device':s.st_dev,'file_index':s.st_ino,'native_acl_verified':False,'power_loss_verified':False}
