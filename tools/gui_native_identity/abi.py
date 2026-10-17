"""Bounded Win32 evidence decoders; in-memory bytes only, never DLL calls.

FILE_ID_INFO/FILE_STANDARD_INFO/FILE_BASIC_INFO and FILETIME layouts are little
endian Windows layouts. SID copies are provider-copied pointees, NOT serialized
native pointers; native pointer/buffer validation is a future binder blocker.
"""
import struct
from .protocol import need,integer
def raw_hex(value,max_bytes=65536):
 need(type(value) is str and len(value)%2==0 and len(value)<=max_bytes*2,'RAW_HEX_BOUND')
 try:b=bytes.fromhex(value)
 except ValueError as exc:raise ValueError('RAW_HEX') from exc
 need(b.hex()==value,'CANONICAL_RAW_HEX');return b
def utf16(value,max_units=512):
 b=raw_hex(value,max_units*2);need(len(b)%2==0 and len(b)>=2 and b[-2:]==b'\0\0','UTF16_TERMINATOR')
 text=b[:-2].decode('utf-16-le',errors='strict');need('\0' not in text and text,'UTF16_EMPTY_OR_NUL');return text
def file_id(value):
 b=raw_hex(value,24);need(len(b)==24,'FILE_ID_INFO_LAYOUT');return {'volume_serial':format(struct.unpack('<Q',b[:8])[0],'016x'),'file_id':b[8:].hex()}
def file_standard(value):
 b=raw_hex(value,24);need(len(b)==24,'FILE_STANDARD_INFO_LAYOUT');allocation,size,links,deleted,directory=struct.unpack('<qqIBB2x',b)
 need(allocation>=size>=0 and links>=1 and deleted==directory==0,'FILE_STANDARD_INFO_UNSAFE');return {'size':size,'links':links}
def file_basic(value):
 b=raw_hex(value,40);need(len(b)==40,'FILE_BASIC_INFO_LAYOUT');creation,access,write,change,attributes=struct.unpack('<qqqqI4x',b)
 need(all(v>=0 for v in [creation,access,write,change]) and not attributes&1024,'FILE_REPARSE_OR_TIME_UNKNOWN');return {'creation':creation,'access':access,'write':write,'change':change,'attributes':attributes}
def process_creation(value):
 b=raw_hex(value,32);need(len(b)==32,'GET_PROCESS_TIMES_LAYOUT');lo,hi,*_=struct.unpack('<8I',b);x=(hi<<32)|lo;need(integer(x,1),'PROCESS_CREATION_REQUIRED');return x
def owner_pair(value):
 b=raw_hex(value,8);need(len(b)==8,'WINDOW_OWNER_LAYOUT');tid,pid=struct.unpack('<II',b);need(tid>0 and pid>0,'WINDOW_OWNER_UNKNOWN');return tid,pid
def sid(value):
 b=raw_hex(value,68);need(len(b)>=8 and b[0]==1 and 1<=b[1]<=15 and len(b)==8+4*b[1],'SID_COPY_LAYOUT');authority=int.from_bytes(b[2:8],'big');subs=struct.unpack('<'+'I'*b[1],b[8:]);return 'S-1-'+str(authority)+'-'+ '-'.join(map(str,subs))
