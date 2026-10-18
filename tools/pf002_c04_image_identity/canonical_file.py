"""Fixed native file contract. Pure decoders; native provider only after signed Job guard."""
import re,struct,time
import model
SCHEMA='C04_WINDOWS_FILE_IDENTITY_V1'
FIELDS=('volume_serial_u64','file_id_128_le','file_size_bytes','creation_time_100ns','change_time_100ns','last_write_time_100ns','file_attributes_u32','number_of_links')
PHASES=('OPENED_BEFORE','OPENED_AFTER_HASH','PATH_REOPENED_BEFORE','PATH_REOPENED_AFTER','OPENED_FINAL')
SIZES={0:40,1:24,18:24}
ERROR_CODES=frozenset(('FILE_INFO_CLASS','FILE_INFO_BUFFER','FILE_BASIC_VALUES','FILE_ID_VALUES','FILE_STANDARD_VALUES','CANONICAL_FIELDS','CANONICAL_SOURCE','CANONICAL_VALUE','CANONICAL_PHASES','CANONICAL_HANDLE_CHANGED','CANONICAL_PATH_NOT_REOPENED','CANONICAL_HASH_BINDING','CANONICAL_FILE_IDENTITY_CHANGED','FILE_API_ABI','FILE_API_FAILED','FILE_FD_HANDLE_UNKNOWN','FILE_QUERY_DEADLINE','FILE_CLOSE_UNKNOWN','NATIVE_PROVIDER_REQUIRED','STAGE_A_REQUIRED','STAGE_A_ROOT_CHANGED'))
def need(ok,code):model.need(ok,code)
def integer(v,lower,upper):return type(v) is int and lower<=v<=upper
def error_number(v):return v if integer(v,-2**31,2**32-1) else None
def decode(info_class,raw):
 need(type(info_class) is int and info_class in SIZES,'FILE_INFO_CLASS')
 need(type(raw) is bytes and len(raw)==SIZES[info_class],'FILE_INFO_BUFFER')
 if info_class==0:
  creation,access,write,change,attrs=struct.unpack('<4qI4x',raw)
  need(all(integer(v,1,2**63-1) for v in (creation,write,change)) and integer(access,0,2**63-1) and not(attrs&0x410),'FILE_BASIC_VALUES')
  return {'creation_time_100ns':creation,'last_access_time_100ns':access,'last_write_time_100ns':write,'change_time_100ns':change,'file_attributes_u32':attrs}
 if info_class==18:
  volume,identifier=struct.unpack('<Q16s',raw);need(volume>0 and identifier!=b'\0'*16,'FILE_ID_VALUES')
  return {'volume_serial_u64':volume,'file_id_128_le':identifier.hex()}
 allocation,size,links,pending,directory=struct.unpack('<qqIBB2x',raw)
 need(all(integer(v,0,2**63-1) for v in (allocation,size)) and 0<size<=32*1024*1024 and links>0 and pending==directory==0,'FILE_STANDARD_VALUES')
 return {'allocation_size_bytes':allocation,'file_size_bytes':size,'number_of_links':links,'delete_pending':False,'directory':False}
def identity(basic,identifier,standard):
 row={**basic,**identifier,**standard};result={field:row[field] for field in FIELDS};validate(result);return result
def validate(row):
 need(type(row) is dict and set(row)==set(FIELDS),'CANONICAL_FIELDS')
 for name in ('creation_time_100ns','change_time_100ns','last_write_time_100ns'):need(integer(row[name],1,2**63-1),'CANONICAL_VALUE')
 need(integer(row['volume_serial_u64'],1,2**64-1) and type(row['file_id_128_le']) is str and re.fullmatch('[0-9a-f]{32}',row['file_id_128_le']) and int(row['file_id_128_le'],16)>0,'CANONICAL_VALUE')
 need(integer(row['file_size_bytes'],1,32*1024*1024) and integer(row['number_of_links'],1,2**32-1) and integer(row['file_attributes_u32'],0,2**32-1) and not(row['file_attributes_u32']&0x410),'CANONICAL_VALUE')
 return row
def compare(observations,hash_info):
 need(type(observations) is list and len(observations)==5 and [o['phase'] for o in observations]==list(PHASES),'CANONICAL_PHASES')
 for row in observations:
  need(row['schema']==SCHEMA and row['api']=='GetFileInformationByHandleEx' and row['time_units']=='FILETIME_100NS_1601_UTC','CANONICAL_SOURCE');validate(row['identity'])
  need(integer(row['file_descriptor'],0,2**31-1) and integer(row['native_handle'],1,2**64-2),'CANONICAL_HANDLE_CHANGED')
 first=observations[0];path=observations[2]
 need(all((o['file_descriptor'],o['native_handle'])==(first['file_descriptor'],first['native_handle']) for o in (observations[1],observations[4])) and (observations[3]['file_descriptor'],observations[3]['native_handle'])==(path['file_descriptor'],path['native_handle']),'CANONICAL_HANDLE_CHANGED')
 need(path['native_handle']!=first['native_handle'] and path['file_descriptor']!=first['file_descriptor'],'CANONICAL_PATH_NOT_REOPENED')
 need(type(hash_info) is dict and set(hash_info)=={'bytes','sha256'} and type(hash_info['bytes']) is int and hash_info['bytes']==first['identity']['file_size_bytes'] and type(hash_info['sha256']) is str and re.fullmatch('[0-9a-f]{64}',hash_info['sha256']),'CANONICAL_HASH_BINDING')
 mismatches={o['phase']:[field for field in FIELDS if first['identity'][field]!=o['identity'][field]] for o in observations[1:]}
 return {'equal':not any(mismatches.values()),'mismatch_fields':mismatches,'identity':dict(first['identity']),'hash':dict(hash_info),'source_schema':SCHEMA,'atomic_snapshot':False,'loaded_image_attestation':False,'compared_fields':list(FIELDS)}
def same_across_process_observations(a,b):
 for row in (a,b):
  need(row['disk_image']['canonical_source_schema']==SCHEMA,'CANONICAL_SOURCE');validate(row['disk_image']['canonical_identity'])
 return all(a[k]==b[k] for k in ('pid','creation_time_100ns','image_path')) and a['disk_image']['canonical_identity']==b['disk_image']['canonical_identity'] and a['disk_image']['sha256']==b['disk_image']['sha256']

class NativeReader:
 """Uses the authenticated Probe's already-created kernel32 provider. No standalone CLI."""
 def __init__(self,provider):
  need(getattr(provider,'_signed_file_provider_ready',False) is True,'NATIVE_PROVIDER_REQUIRED')
  self.provider=provider;self.c=provider.c;self.w=provider.w;self.k=provider.k;self.emit=provider.emit
  c,w=self.c,self.w
  class BASIC(c.Structure):_fields_=[('CreationTime',c.c_longlong),('LastAccessTime',c.c_longlong),('LastWriteTime',c.c_longlong),('ChangeTime',c.c_longlong),('FileAttributes',w.DWORD)]
  class ID(c.Structure):_fields_=[('VolumeSerialNumber',c.c_ulonglong),('FileId',c.c_ubyte*16)]
  class STANDARD(c.Structure):_fields_=[('AllocationSize',c.c_longlong),('EndOfFile',c.c_longlong),('NumberOfLinks',w.DWORD),('DeletePending',c.c_ubyte),('Directory',c.c_ubyte)]
  self.types={0:BASIC,1:STANDARD,18:ID}
  offsets={'basic_creation':BASIC.CreationTime.offset,'basic_access':BASIC.LastAccessTime.offset,'basic_write':BASIC.LastWriteTime.offset,'basic_change':BASIC.ChangeTime.offset,'basic_attributes':BASIC.FileAttributes.offset,'id_volume':ID.VolumeSerialNumber.offset,'id_identifier':ID.FileId.offset,'standard_allocation':STANDARD.AllocationSize.offset,'standard_size':STANDARD.EndOfFile.offset,'standard_links':STANDARD.NumberOfLinks.offset,'standard_delete':STANDARD.DeletePending.offset,'standard_directory':STANDARD.Directory.offset}
  need(c.sizeof(w.DWORD)==4 and c.sizeof(w.BOOL)==4 and c.sizeof(w.HANDLE)==c.sizeof(c.c_void_p) and c.sizeof(c.c_void_p) in (4,8) and all(c.sizeof(t)==SIZES[k] for k,t in self.types.items()) and offsets=={'basic_creation':0,'basic_access':8,'basic_write':16,'basic_change':24,'basic_attributes':32,'id_volume':0,'id_identifier':8,'standard_allocation':0,'standard_size':8,'standard_links':16,'standard_delete':20,'standard_directory':21},'FILE_API_ABI')
  self.emit('FILE_API_ABI',{'pointer_bytes':c.sizeof(c.c_void_p),'DWORD_bytes':4,'BOOL_bytes':4,'sizes':{str(k):c.sizeof(t) for k,t in self.types.items()},'offsets':offsets,'padding_not_identity':True})
  f=self.k.GetFileInformationByHandleEx;f.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];f.restype=w.BOOL
 def bounded(self):need(time.monotonic()<=self.provider.end,'FILE_QUERY_DEADLINE')
 def query(self,handle,info_class,phase):
  need(type(info_class) is int and info_class in SIZES,'FILE_INFO_CLASS');self.bounded()
  row=self.types[info_class]();need(self.c.sizeof(row)==SIZES[info_class],'FILE_API_ABI');start=time.monotonic_ns();self.c.set_last_error(0)
  result=self.k.GetFileInformationByHandleEx(handle,info_class,self.c.byref(row),self.c.sizeof(row));error=None if result else self.c.get_last_error()
  raw=self.c.string_at(self.c.byref(row),self.c.sizeof(row));self.emit('FILE_NATIVE_QUERY',{'phase':phase,'api':'GetFileInformationByHandleEx','information_class':info_class,'native_handle':int(handle),'raw_return':int(result),'ok':bool(result),'win32_error':error_number(error),'buffer_capacity_bytes':len(raw),'returned_length_available':False,'raw_hex':raw.hex(),'start_monotonic_ns':start,'end_monotonic_ns':time.monotonic_ns()})
  need(bool(result),'FILE_API_FAILED');return decode(info_class,raw)
 def snapshot(self,fd,phase):
  need(type(fd) is int and 0<=fd<2**31 and phase in PHASES,'FILE_FD_HANDLE_UNKNOWN');self.bounded()
  # Borrow only. Python file objects retain ownership; never CloseHandle this value.
  import msvcrt
  start=time.monotonic_ns()
  try:handle=msvcrt.get_osfhandle(fd)
  except OSError as exc:
   self.emit('FILE_DESCRIPTOR_HANDLE',{'phase':phase,'file_descriptor':fd,'status':'UNKNOWN','errno':error_number(exc.errno),'win32_error':error_number(getattr(exc,'winerror',None))});raise
  need(type(handle) is int and 0<handle<2**(8*self.c.sizeof(self.w.HANDLE))-1,'FILE_FD_HANDLE_UNKNOWN')
  self.emit('FILE_DESCRIPTOR_HANDLE',{'phase':phase,'file_descriptor':fd,'native_handle':handle,'status':'OK','source':'msvcrt.get_osfhandle','borrowed_not_closed_by_native_provider':True,'start_monotonic_ns':start,'end_monotonic_ns':time.monotonic_ns()})
  basic=self.query(handle,0,phase);identifier=self.query(handle,18,phase);standard=self.query(handle,1,phase)
  row={'phase':phase,'schema':SCHEMA,'api':'GetFileInformationByHandleEx','time_units':'FILETIME_100NS_1601_UTC','file_descriptor':fd,'native_handle':handle,'identity':identity(basic,identifier,standard),'raw_last_access_time_100ns':basic['last_access_time_100ns'],'allocation_size_bytes':standard['allocation_size_bytes']}
  self.emit('FILE_IDENTITY_SNAPSHOT',row);self.bounded();return row
