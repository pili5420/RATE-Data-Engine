"""Exact API/field/right declarations for the candidate's synthetic-only boundary."""
KIND='OFFLINE_NATIVE_IDENTITY_MODEL_NO_EXECUTION_AUTHORITY'
PROVIDER_KIND='SYNTHETIC_WINDOWS_API_DATA_ONLY'
WITNESS_KIND='SYNTHETIC_VERIFIABLE_LIFECYCLE_LEDGER'
FINAL_GATE='BLOCKED_PENDING_SEPARATE_NATIVE_QUALIFICATION_AND_REAL_IDENTITY_AUTHORIZATION'
API_FIELDS={
 'GetComputerNameExW':('host',), 'GetCurrentProcessId':('observer_pid',), 'GetCurrentThreadId':('observer_tid',),
 'ProcessIdToSessionId':('session_id',), 'GetProcessWindowStation':('observer_station',),
 'GetThreadDesktop':('desktop',), 'GetUserObjectInformationW':('desktop','observer_station'),
 'EnumWindows':('hwnd','enumeration_complete'), 'IsWindow':('hwnd',),
 'GetWindowThreadProcessId':('hwnd','pid','tid'), 'GetClassNameW':('class_name',),
 'OpenProcess':('pid',), 'GetProcessTimes':('creation_filetime_100ns',),
 'QueryFullProcessImageNameW':('executable_path',), 'OpenProcessToken':('token',),
 'GetTokenInformation':('token',), 'CreateFileW':('executable_path',),
 'GetFinalPathNameByHandleW':('executable_path',), 'GetFileInformationByHandleEx':('file_identity','file_metadata'),
 'ReadFile':('executable_sha256',), 'CloseHandle':(),
}
RIGHTS={'process':4096,'token':8,'file':129}
ARG_KEYS={'GetComputerNameExW':('format','capacity'),'GetCurrentProcessId':(),'GetCurrentThreadId':(),'GetProcessWindowStation':(),
 'ProcessIdToSessionId':('pid',),'GetThreadDesktop':('tid',),'GetUserObjectInformationW':('handle','index','capacity'),
 'EnumWindows':('max_windows',),'IsWindow':('hwnd',),'GetWindowThreadProcessId':('hwnd',),'GetClassNameW':('hwnd',),
 'OpenProcess':('pid','desired_access','inherit'),'GetProcessTimes':('handle',),'QueryFullProcessImageNameW':('handle','capacity','flags'),
 'OpenProcessToken':('handle','desired_access'),'GetTokenInformation':('handle','class'),
 'CreateFileW':('path','desired_access','share','disposition','flags'),'GetFinalPathNameByHandleW':('handle','capacity','flags'),
 'GetFileInformationByHandleEx':('handle','class'),'ReadFile':('handle','offset','count'),'CloseHandle':('handle',)}
SCOPE={'stage':'IDENTITY_ONLY','apis':sorted(API_FIELDS),'api_fields':{k:list(v) for k,v in API_FIELDS.items()},
 'access_rights':RIGHTS,'file_share_mode':7,'file_disposition':3,'file_flags':0x00200000,
 'no_titles':True,'no_memory_reads':True,'no_diagnostic_promotion':True,'native_execution_authorized':False}
RUNTIME_FILES=('__init__.py','contracts.py','protocol.py','baseline.py','abi.py','provider.py','witness.py','journal.py','adapter.py')
BASELINE_TOOL_SHA='84c92cb86755892054ae79d49a9dca124d31d921a0daf2a89fa620bfbe690460'
BASELINE_HEAD='2e4e24c3a4f73d6fabe3881f4962c919d0a21c69'
