"""Windows model layouts and owned byte arenas; never reads native addresses.

Both ABIs use Windows LLP64 with default MSVC pack8. No host ctypes layout is
mistaken for x86 proof. Golden layouts are engineering vectors, not SDK builds.
"""
import struct
from .protocol import require,exact,uint,rawhex,digest
LAYOUTS={
 'win32':{'pointer':4,'DWORD':4,'BOOL':4,'FILETIME':8,'SID_AND_ATTRIBUTES':8,'SID_ATTRIBUTES_OFFSET':4,'TOKEN_GROUPS_OFFSET':4,'TOKEN_GROUPS_STRIDE':8,'TOKEN_MANDATORY_LABEL':8,'FILE_ID_INFO':24,'FILE_STANDARD_INFO':24,'FILE_BASIC_INFO':40},
 'win64':{'pointer':8,'DWORD':4,'BOOL':4,'FILETIME':8,'SID_AND_ATTRIBUTES':16,'SID_ATTRIBUTES_OFFSET':8,'TOKEN_GROUPS_OFFSET':8,'TOKEN_GROUPS_STRIDE':16,'TOKEN_MANDATORY_LABEL':16,'FILE_ID_INFO':24,'FILE_STANDARD_INFO':24,'FILE_BASIC_INFO':40}}
def layout(abi):require(type(abi) is str and abi in LAYOUTS,'ABI_NOT_WINDOWS_X86_OR_X64');return dict(LAYOUTS[abi])
def word(data,size):require(type(data) is bytes and len(data)==size,'WIRE_WORD_SIZE');return int.from_bytes(data,'little')
def dword(value):require(uint(value,32),'DWORD_NATIVE_INTEGER');return value
def handle(value,abi):bits=layout(abi)['pointer']*8;require(uint(value,bits,1) and value!=2**bits-1,'HANDLE_NULL_INVALID_OR_WIDTH');return value
def filetime(raw):
 data=rawhex(raw,8);require(len(data)==8,'FILETIME_LAYOUT');lo,hi=struct.unpack('<II',data);return lo|(hi<<32)
def utf16(raw,count,capacity,nonempty=True):
 require(uint(count,32) and uint(capacity,32,2) and capacity<=32768 and count<capacity-1,'UTF16_TRUNCATED_OR_COUNT_UNKNOWN','INDETERMINATE')
 data=rawhex(raw,capacity*2);require(len(data)==(count+1)*2 and data[-2:]==b'\0\0','UTF16_LENGTH_OR_TERMINATOR')
 text=data[:-2].decode('utf-16-le','strict');require('\0' not in text and (bool(text) or not nonempty),'UTF16_NUL_OR_EMPTY');require(len(text.encode('utf-16-le'))==count*2,'UTF16_CODE_UNIT_COUNT');return text
def sid(raw):
 require(type(raw) is bytes and 8<=len(raw)<=68 and raw[0]==1 and raw[1]<=15 and len(raw)==8+4*raw[1],'SID_LAYOUT')
 authority=int.from_bytes(raw[2:8],'big');subs=struct.unpack('<'+'I'*raw[1],raw[8:])
 return 'S-1-'+str(authority)+''.join('-'+str(v) for v in subs)

class ByteArena:
 """Owned immutable synthetic allocations, with initialized extent and leases."""
 def __init__(self,abi,owner,allocations):
  self.abi=abi;self.bits=layout(abi)['pointer']*8;require(type(owner) is str and owner.startswith('SYNTHETIC-'),'SYNTHETIC_BUFFER_OWNER');self.owner=owner;self.rows={};self.closed=False;self.reads=[];require(type(allocations) is list and len(allocations)<=16,'ALLOCATION_COUNT_BOUND')
  spans=[]
  for row in allocations:
   exact(row,{'id','owner','generation','base','capacity','initialized','data_hex'})
   require(type(row['id']) is str and row['id'] and row['id'] not in self.rows and row['owner']==owner,'BUFFER_ID_OWNER')
   require(uint(row['generation'],32,1) and uint(row['base'],self.bits,4096) and uint(row['capacity'],32,1) and row['capacity']<=1048576 and uint(row['initialized'],32) and row['initialized']<=row['capacity'],'BUFFER_METADATA')
   require(row['base']+row['capacity']<=2**self.bits,'POINTER_OVERFLOW');data=rawhex(row['data_hex'],1048576);require(len(data)==row['capacity'],'BUFFER_CAPACITY_BYTES')
   begin,end=row['base'],row['base']+row['capacity'];require(all(end<=a or begin>=b for a,b in spans),'OVERLAPPING_ALLOCATIONS');spans.append((begin,end));self.rows[row['id']]=dict(row)
  self.pin=digest(self.rows)
 def read(self,buffer_id,pointer,length,owner,generation,alignment=1):
  require(not self.closed and digest(self.rows)==self.pin,'BUFFER_CLOSED_OR_MUTATED','INDETERMINATE');require(buffer_id in self.rows,'UNKNOWN_BUFFER');row=self.rows[buffer_id]
  require(owner==self.owner==row['owner'] and type(generation) is int and generation==row['generation'],'BUFFER_OWNER_OR_LEASE')
  require(uint(pointer,self.bits,1) and uint(length,32) and type(alignment) is int and alignment in {1,2,4,8} and pointer%alignment==0,'POINTER_WIDTH_LENGTH_OR_ALIGNMENT')
  require(pointer+length<=2**self.bits and row['base']<=pointer<=pointer+length<=row['base']+row['initialized'],'POINTER_OUTSIDE_INITIALIZED_OWNED_BUFFER')
  self.reads.append({'buffer':buffer_id,'address':pointer,'bytes':length});offset=pointer-row['base'];return bytes.fromhex(row['data_hex'])[offset:offset+length]
 def close(self):require(not self.closed,'BUFFER_DOUBLE_RELEASE');self.closed=True

def token_groups(arena,buffer_id,generation,mandatory=False):
 require(type(arena) is ByteArena,'EXACT_SYNTHETIC_ARENA');row=arena.rows[buffer_id];base=row['base'];l=layout(arena.abi);ptr=l['pointer'];owner=arena.owner
 read=lambda offset,length,alignment=1:arena.read(buffer_id,base+offset,length,owner,generation,alignment)
 if mandatory:count=1;offset=0;table_end=l['TOKEN_MANDATORY_LABEL']
 else:count=word(read(0,4,4),4);require(1<=count<=256,'TOKEN_GROUP_COUNT_BOUND');offset=l['TOKEN_GROUPS_OFFSET'];table_end=offset+count*l['TOKEN_GROUPS_STRIDE']
 read(0,table_end);groups=[];spans=[]
 for i in range(count):
  slot=offset+i*l['TOKEN_GROUPS_STRIDE'];pointer=word(read(slot,ptr,ptr),ptr);attrs=word(read(slot+ptr,4,4),4)
  require(pointer>=base+table_end,'SID_POINTER_ALIASES_HEADER')
  header=arena.read(buffer_id,pointer,8,owner,generation,4);require(header[0]==1 and header[1]<=15,'SID_HEADER');length=8+4*header[1];raw=arena.read(buffer_id,pointer,length,owner,generation,4);value=sid(raw)
  require(all(pointer+length<=a or pointer>=b for a,b in spans),'OVERLAPPING_SID_POINTEES');spans.append((pointer,pointer+length));require(value not in [x['sid'] for x in groups],'DUPLICATE_TOKEN_SID')
  groups.append({'sid':value,'attributes':attrs})
 return groups

class HandleTable:
 def __init__(self,abi,owner):self.abi=abi;self.owner=owner;self.entries={}
 def register(self,value,kind,generation,borrowed=False):
  handle(value,self.abi);require(type(kind) is str and kind in {'process','token','file','desktop','station'} and uint(generation,32,1) and type(borrowed) is bool,'HANDLE_METADATA');require(value not in self.entries,'HANDLE_REUSE_OR_DUPLICATE');self.entries[value]={'kind':kind,'generation':generation,'borrowed':borrowed,'closed':False}
 def require(self,value,kind,generation):
  handle(value,self.abi);require(value in self.entries,'UNREGISTERED_HANDLE');row=self.entries[value];require(not row['closed'] and row['kind']==kind and type(generation) is int and row['generation']==generation,'HANDLE_KIND_LEASE_OR_CLOSED');return row
 def close(self,value,kind,generation):
  row=self.require(value,kind,generation);require(not row['borrowed'],'BORROWED_HANDLE_MUST_NOT_CLOSE');row['closed']=True
