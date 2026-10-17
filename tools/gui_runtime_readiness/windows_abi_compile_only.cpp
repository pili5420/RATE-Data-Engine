// Compile-only translation unit. No main, DllMain, function body, callback,
// native dispatch, imported-function address initialization or link step.
// Compile separately with genuine x86 and x64 MSVC + Windows SDK, /c /W4 /WX.
// This file was NOT compiled if the environment inventory reports no SDK/cl.
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0602
#endif
#include <windows.h>
#include <type_traits>
#include <cstddef>

static_assert(sizeof(DWORD)==4 && sizeof(BOOL)==4 && sizeof(FILETIME)==8);
static_assert(sizeof(FILE_ID_INFO)==24 && sizeof(FILE_BASIC_INFO)==40);
static_assert(sizeof(FILE_STANDARD_INFO)==24);
static_assert(offsetof(SID_AND_ATTRIBUTES,Attributes)==sizeof(void*));
static_assert(offsetof(JOBOBJECT_BASIC_LIMIT_INFORMATION,LimitFlags)==16);
#if defined(_WIN64)
static_assert(sizeof(void*)==8 && sizeof(SID_AND_ATTRIBUTES)==16);
static_assert(offsetof(TOKEN_GROUPS,Groups)==8);
static_assert(sizeof(JOBOBJECT_BASIC_LIMIT_INFORMATION)==64);
static_assert(sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)==144);
#else
static_assert(sizeof(void*)==4 && sizeof(SID_AND_ATTRIBUTES)==8);
static_assert(offsetof(TOKEN_GROUPS,Groups)==4);
static_assert(sizeof(JOBOBJECT_BASIC_LIMIT_INFORMATION)==48);
static_assert(sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)==112);
#endif
#define ABI_CHECK(name,ret,...) static_assert(std::is_same_v<decltype(&::name),ret(WINAPI*)(__VA_ARGS__)>);
ABI_CHECK(GetComputerNameExW,BOOL,COMPUTER_NAME_FORMAT,LPWSTR,LPDWORD)
ABI_CHECK(GetCurrentProcessId,DWORD,void)
ABI_CHECK(GetCurrentThreadId,DWORD,void)
ABI_CHECK(ProcessIdToSessionId,BOOL,DWORD,LPDWORD)
ABI_CHECK(GetProcessWindowStation,HWINSTA,void)
ABI_CHECK(GetThreadDesktop,HDESK,DWORD)
ABI_CHECK(GetUserObjectInformationW,BOOL,HANDLE,int,PVOID,DWORD,LPDWORD)
ABI_CHECK(EnumWindows,BOOL,WNDENUMPROC,LPARAM)
ABI_CHECK(IsWindow,BOOL,HWND)
ABI_CHECK(GetWindowThreadProcessId,DWORD,HWND,LPDWORD)
ABI_CHECK(GetClassNameW,int,HWND,LPWSTR,int)
ABI_CHECK(OpenProcess,HANDLE,DWORD,BOOL,DWORD)
ABI_CHECK(GetProcessTimes,BOOL,HANDLE,LPFILETIME,LPFILETIME,LPFILETIME,LPFILETIME)
ABI_CHECK(QueryFullProcessImageNameW,BOOL,HANDLE,DWORD,LPWSTR,PDWORD)
ABI_CHECK(OpenProcessToken,BOOL,HANDLE,DWORD,PHANDLE)
ABI_CHECK(GetTokenInformation,BOOL,HANDLE,TOKEN_INFORMATION_CLASS,LPVOID,DWORD,PDWORD)
ABI_CHECK(CreateFileW,HANDLE,LPCWSTR,DWORD,DWORD,LPSECURITY_ATTRIBUTES,DWORD,DWORD,HANDLE)
ABI_CHECK(GetFinalPathNameByHandleW,DWORD,HANDLE,LPWSTR,DWORD,DWORD)
ABI_CHECK(GetFileInformationByHandleEx,BOOL,HANDLE,FILE_INFO_BY_HANDLE_CLASS,LPVOID,DWORD)
ABI_CHECK(ReadFile,BOOL,HANDLE,LPVOID,DWORD,LPDWORD,LPOVERLAPPED)
ABI_CHECK(CloseHandle,BOOL,HANDLE)
ABI_CHECK(CreateJobObjectW,HANDLE,LPSECURITY_ATTRIBUTES,LPCWSTR)
ABI_CHECK(SetInformationJobObject,BOOL,HANDLE,JOBOBJECTINFOCLASS,LPVOID,DWORD)
ABI_CHECK(AssignProcessToJobObject,BOOL,HANDLE,HANDLE)
ABI_CHECK(QueryInformationJobObject,BOOL,HANDLE,JOBOBJECTINFOCLASS,LPVOID,DWORD,LPDWORD)
ABI_CHECK(TerminateJobObject,BOOL,HANDLE,UINT)
ABI_CHECK(CancelSynchronousIo,BOOL,HANDLE)
ABI_CHECK(WaitForSingleObject,DWORD,HANDLE,DWORD)
