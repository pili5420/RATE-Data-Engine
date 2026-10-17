"""Complete declarative identity API bindings; intentionally no FFI loader.

Types/directions/ownership are executable validation data, not callable Windows
addresses. Native binding/dispatch is unavailable even after offline admission.
"""
from gui_native_preflight.protocol import require, exact, uint, digest
from gui_native_preflight.abi import layout, handle

# name: (DLL, return type, parameter types). WINAPI is stdcall on x86 and the
# Windows x64 convention on x64. No platform-dependent host ctypes is used.
PROTOTYPES = {
 'GetComputerNameExW': ('kernel32.dll','BOOL',('COMPUTER_NAME_FORMAT','OUT_UTF16','INOUT_DWORD')),
 'GetCurrentProcessId': ('kernel32.dll','DWORD',()),
 'GetCurrentThreadId': ('kernel32.dll','DWORD',()),
 'ProcessIdToSessionId': ('kernel32.dll','BOOL',('DWORD','OUT_DWORD')),
 'GetProcessWindowStation': ('user32.dll','BORROWED_HWINSTA',()),
 'GetThreadDesktop': ('user32.dll','BORROWED_HDESK',('DWORD',)),
 'GetUserObjectInformationW': ('user32.dll','BOOL',('HANDLE','INT32','OUT_BYTES','DWORD','OUT_DWORD')),
 'EnumWindows': ('user32.dll','BOOL',('WNDENUMPROC','LPARAM')),
 'IsWindow': ('user32.dll','BOOL',('HWND',)),
 'GetWindowThreadProcessId': ('user32.dll','DWORD',('HWND','OUT_DWORD')),
 'GetClassNameW': ('user32.dll','INT32',('HWND','OUT_UTF16','INT32')),
 'OpenProcess': ('kernel32.dll','OWNED_HANDLE',('DWORD','BOOL','DWORD')),
 'GetProcessTimes': ('kernel32.dll','BOOL',('HANDLE','OUT_FILETIME','OUT_FILETIME','OUT_FILETIME','OUT_FILETIME')),
 'QueryFullProcessImageNameW': ('kernel32.dll','BOOL',('HANDLE','DWORD','OUT_UTF16','INOUT_DWORD')),
 'OpenProcessToken': ('advapi32.dll','BOOL',('HANDLE','DWORD','OUT_HANDLE')),
 'GetTokenInformation': ('advapi32.dll','BOOL',('HANDLE','TOKEN_INFORMATION_CLASS','OUT_BYTES','DWORD','OUT_DWORD')),
 'CreateFileW': ('kernel32.dll','OWNED_HANDLE',('IN_UTF16','DWORD','DWORD','NULL_SECURITY_ATTRIBUTES','DWORD','DWORD','NULL_TEMPLATE_HANDLE')),
 'GetFinalPathNameByHandleW': ('kernel32.dll','DWORD',('HANDLE','OUT_UTF16','DWORD','DWORD')),
 'GetFileInformationByHandleEx': ('kernel32.dll','BOOL',('HANDLE','FILE_INFO_BY_HANDLE_CLASS','OUT_BYTES','DWORD')),
 'ReadFile': ('kernel32.dll','BOOL',('HANDLE','OUT_BYTES','DWORD','OUT_DWORD','NULL_OVERLAPPED')),
 'CloseHandle': ('kernel32.dll','BOOL',('OWNED_HANDLE',)),
}
CONTAINMENT_PROTOTYPES = {
 'CreateJobObjectW': ('kernel32.dll','OWNED_HANDLE',('NULL_SECURITY_ATTRIBUTES','NULL_NAME')),
 'SetInformationJobObject': ('kernel32.dll','BOOL',('HANDLE','JOBOBJECTINFOCLASS','IN_BYTES','DWORD')),
 'AssignProcessToJobObject': ('kernel32.dll','BOOL',('HANDLE','HANDLE')),
 'QueryInformationJobObject': ('kernel32.dll','BOOL',('HANDLE','JOBOBJECTINFOCLASS','OUT_BYTES','DWORD','OUT_DWORD')),
 'TerminateJobObject': ('kernel32.dll','BOOL',('HANDLE','UINT32')),
 'CancelSynchronousIo': ('kernel32.dll','BOOL',('HANDLE',)),
 'WaitForSingleObject': ('kernel32.dll','DWORD',('HANDLE','DWORD')),
}
# Supporting declarations are never added to the identity read-call allowlist.
# Process creation/security/root flushing remain native-unqualified designs.
SUPPORT_PROTOTYPES = {
 'GetLastError':('kernel32.dll','DWORD',()),
 'SetLastError':('kernel32.dll','VOID',('DWORD',)),
 'CreateProcessW':('kernel32.dll','BOOL',('LPCWSTR','INOUT_LPWSTR','NULL_PROCESS_SECURITY','NULL_THREAD_SECURITY','BOOL','DWORD','ENVIRONMENT_BLOCK','LPCWSTR','STARTUPINFOW','OUT_PROCESS_INFORMATION')),
 'ResumeThread':('kernel32.dll','DWORD',('HANDLE',)),
 'GetExitCodeProcess':('kernel32.dll','BOOL',('HANDLE','OUT_DWORD')),
 'GetProcessId':('kernel32.dll','DWORD',('HANDLE',)),
 'GetSecurityInfo':('advapi32.dll','DWORD',('HANDLE','SE_OBJECT_TYPE','SECURITY_INFORMATION','OUT_PSID','OUT_PSID','OUT_PACL','OUT_PACL','OUT_SECURITY_DESCRIPTOR')),
 'LocalFree':('kernel32.dll','HLOCAL',('HLOCAL',)),
 'FlushFileBuffers':('kernel32.dll','BOOL',('HANDLE',)),
 'InitializeProcThreadAttributeList':('kernel32.dll','BOOL',('ATTRIBUTE_LIST','DWORD','DWORD','INOUT_SIZE_T')),
 'UpdateProcThreadAttribute':('kernel32.dll','BOOL',('ATTRIBUTE_LIST','DWORD','DWORD_PTR','LPVOID','SIZE_T','NULL_PREVIOUS_VALUE','NULL_RETURN_SIZE')),
 'DeleteProcThreadAttributeList':('kernel32.dll','VOID',('ATTRIBUTE_LIST',)),
}
FIELDS = {
 'GetComputerNameExW': ('host',), 'GetCurrentProcessId': ('observer_pid',),
 'GetCurrentThreadId': ('observer_tid',), 'ProcessIdToSessionId': ('session',),
 'GetProcessWindowStation': ('station_handle',), 'GetThreadDesktop': ('desktop_handle',),
 'GetUserObjectInformationW': ('object_name',), 'EnumWindows': ('hwnds','complete'),
 'IsWindow': ('exists',), 'GetWindowThreadProcessId': ('pid','tid'),
 'GetClassNameW': ('class_name',), 'OpenProcess': ('process_handle',),
 'GetProcessTimes': ('creation','exit','kernel','user'),
 'QueryFullProcessImageNameW': ('executable_path',), 'OpenProcessToken': ('token_handle',),
 'GetTokenInformation': ('token',), 'CreateFileW': ('file_handle',),
 'GetFinalPathNameByHandleW': ('final_path',),
 'GetFileInformationByHandleEx': ('file_info',), 'ReadFile': ('data_hex',),
 'CloseHandle': ('closed',),
}
ARGS = {
 'GetComputerNameExW': {'format','capacity'}, 'GetCurrentProcessId': set(),
 'GetCurrentThreadId': set(), 'ProcessIdToSessionId': {'pid'},
 'GetProcessWindowStation': set(), 'GetThreadDesktop': {'tid'},
 'GetUserObjectInformationW': {'handle','index','capacity_bytes'},
 'EnumWindows': {'max_windows'}, 'IsWindow': {'hwnd'},
 'GetWindowThreadProcessId': {'hwnd'}, 'GetClassNameW': {'hwnd','capacity'},
 'OpenProcess': {'access','inherit','pid'}, 'GetProcessTimes': {'handle'},
 'QueryFullProcessImageNameW': {'handle','flags','capacity'},
 'OpenProcessToken': {'handle','access'},
 'GetTokenInformation': {'handle','info_class','buffer_bytes'},
 'CreateFileW': {'path','access','share','disposition','flags','inherit'},
 'GetFinalPathNameByHandleW': {'handle','capacity','flags'},
 'GetFileInformationByHandleEx': {'handle','info_class','buffer_bytes'},
 'ReadFile': {'handle','offset','count'}, 'CloseHandle': {'handle','kind','generation'},
}
RIGHTS = {'process':4096, 'token':8, 'file':129}
SYNTHETIC_FILE = r'C:\SYNTHETIC-RQR\Fixture.exe'

def descriptor(api, abi):
    require(api in PROTOTYPES, 'API_NOT_ALLOWED')
    sizes = layout(abi)
    dll, result, parameters = PROTOTYPES[api]
    return {'api':api, 'dll':dll, 'calling_convention':'WINAPI_STDCALL' if abi=='win32' else 'WINDOWS_X64',
            'pointer_bytes':sizes['pointer'], 'DWORD_bytes':4, 'BOOL_bytes':4,
            'return_type':result, 'parameters':list(parameters),
            'fields':list(FIELDS[api]), 'native_qualified':False}

def validate_request(request):
    exact(request, {'api','abi','args','fields','rights'})
    api, abi, args = request['api'], request['abi'], request['args']
    descriptor(api, abi); exact(args, ARGS[api])
    require(request['fields']==list(FIELDS[api]) and digest(request['rights'])==digest(RIGHTS), 'EXACT_READ_SCOPE')
    for key,value in args.items():
        if key in {'kind','path'}:require(type(value) is str, 'STRING_ARGUMENT')
        else:require(uint(value,64), 'NATIVE_INTEGER_ARGUMENT')
    for key in {'handle','hwnd'} & set(args):handle(args[key],abi)
    for key in {'pid','tid'} & set(args):require(uint(args[key],32,1), 'PROCESS_ID_ARGUMENT')
    if 'capacity' in args:require(2<=args['capacity']<=32768,'UTF16_CAPACITY')
    if 'capacity_bytes' in args:require(4<=args['capacity_bytes']<=65536 and args['capacity_bytes']%2==0,'UTF16_BYTE_CAPACITY')
    if 'buffer_bytes' in args:require(1<=args['buffer_bytes']<=1048576,'BUFFER_CAPACITY')
    if api=='GetComputerNameExW':require(args['format']==5,'PHYSICAL_DNS_HOSTNAME_ONLY')
    if api=='GetUserObjectInformationW':require(args['index']==2,'UOI_NAME_ONLY')
    if api=='EnumWindows':require(1<=args['max_windows']<=128,'ENUMERATION_BOUND')
    if api=='OpenProcess':require(args['access']==4096 and args['inherit']==0,'PROCESS_QUERY_ONLY')
    if api=='OpenProcessToken':require(args['access']==8,'TOKEN_QUERY_ONLY')
    if api=='CreateFileW':require(args['path']==SYNTHETIC_FILE and args['access']==129 and args['share']==7 and args['disposition']==3 and args['flags']==0x00200000 and args['inherit']==0,'OPEN_EXISTING_REPARSE_POINT_NONINHERIT_TEST_FILE_ONLY')
    if api=='QueryFullProcessImageNameW':require(args['flags']==0,'IMAGE_FLAGS')
    if api=='GetFinalPathNameByHandleW':require(args['flags']==0,'FINAL_PATH_FLAGS')
    if api=='GetTokenInformation':require(args['info_class'] in {1,2,18,20,25},'TOKEN_QUERY_CLASS')
    if api=='GetFileInformationByHandleEx':require(args['info_class'] in {0,1,18},'FILE_QUERY_CLASS')
    if api=='ReadFile':require(args['offset']<=16777216 and 1<=args['count']<=65536 and args['offset']+args['count']<=16777216,'BOUNDED_FILE_RANGE')
    return descriptor(api,abi)

class NativeBindingUnavailable:
    def bind(self,*args,**kwargs):
        raise RuntimeError('REAL_NATIVE_BINDING_AND_DISPATCH_UNAVAILABLE_NOT_AUTHORIZED')
