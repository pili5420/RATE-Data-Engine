"""Manual-only Fugle free/basic feasibility diagnostic. No Production mutation."""
from __future__ import annotations

import argparse
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.provider_fugle_intraday_candidate import load_binding, qualify

ROOT = Path(__file__).resolve().parents[1]
BINDING_PATH = ROOT / "docs" / "contracts" / "RATE_FUGLE_FREE_INTRADAY_UNIVERSE_BINDING_V1.json"
OUTPUT_PARTS = ("artifacts", "diagnostics", "fugle-free-intraday")
OUTPUT_ROOT = ROOT.joinpath(*OUTPUT_PARTS)


def _load_fixed_binding() -> dict:
    try:
        value = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("FUGLE_DIAGNOSTIC_BINDING_UNREADABLE") from exc
    # Validate the fixed mirror against RATE's authoritative Production universe
    # before credential access or any network request.
    load_binding(value)
    return value


def _validate_output_name(output_name: str) -> None:
    if not isinstance(output_name, str) or not output_name:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_NAME_INVALID")
    if Path(output_name).name != output_name or "/" in output_name or "\\" in output_name:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_PATH_FORBIDDEN")
    if output_name in {".", "..", ".json", "..json"} or not output_name.endswith(".json"):
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_NAME_INVALID")


def _validate_output_layout() -> tuple[Path, Path]:
    root = ROOT.absolute()
    output_root = OUTPUT_ROOT.absolute()
    try:
        relative = output_root.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ROOT_OUTSIDE_REPOSITORY") from exc
    if relative.parts != OUTPUT_PARTS:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ROOT_INVALID")
    return root, output_root


class _TrustedOutput:
    """Pinned diagnostic directory plus exclusive-create writer."""

    def __init__(
        self,
        output_name: str,
        output_root: Path,
        *,
        posix_fds: list[int] | None = None,
        windows_handles: list[int] | None = None,
    ) -> None:
        self.output_name = output_name
        self.output_root = output_root
        self._posix_fds = posix_fds or []
        self._windows_handles = windows_handles or []
        self._closed = False

    @property
    def target_path(self) -> Path:
        return self.output_root / self.output_name

    def __enter__(self) -> "_TrustedOutput":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd in reversed(self._posix_fds):
            try:
                os.close(fd)
            except OSError:
                pass
        self._posix_fds.clear()
        if os.name == "nt":
            for handle in reversed(self._windows_handles):
                try:
                    _win_close_handle(handle)
                except OSError:
                    pass
        self._windows_handles.clear()

    def write_result(self, result: dict) -> None:
        if self._closed:
            raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_SESSION_CLOSED")
        if os.name == "nt":
            if not self._windows_handles:
                raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_SESSION_INVALID")
            _win_write_new(self._windows_handles[-1], self.output_name, result)
            return
        if not self._posix_fds:
            raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_SESSION_INVALID")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.output_name, flags, 0o600, dir_fd=self._posix_fds[-1])
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")


def _open_trusted_output_posix(output_name: str, root: Path, output_root: Path) -> _TrustedOutput:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("FUGLE_DIAGNOSTIC_SECURE_DIRECTORY_API_UNAVAILABLE")
    if os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd or os.stat not in os.supports_dir_fd:
        raise RuntimeError("FUGLE_DIAGNOSTIC_SECURE_DIRECTORY_API_UNAVAILABLE")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fds: list[int] = []
    try:
        root_fd = os.open(root, flags)
        fds.append(root_fd)
        current_fd = root_fd
        for component in OUTPUT_PARTS:
            try:
                child_fd = os.open(component, flags, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    child_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ANCESTRY_UNTRUSTED") from exc
            except OSError as exc:
                raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ANCESTRY_UNTRUSTED") from exc
            if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
                os.close(child_fd)
                raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ANCESTRY_UNTRUSTED")
            fds.append(child_fd)
            current_fd = child_fd

        try:
            os.stat(output_name, dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_EXISTS")
        return _TrustedOutput(output_name, output_root, posix_fds=fds)
    except Exception:
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass
        raise


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _FILE_LIST_DIRECTORY = 0x0001
    _FILE_READ_ATTRIBUTES = 0x0080
    _GENERIC_WRITE = 0x40000000
    _SYNCHRONIZE = 0x00100000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_ATTRIBUTE_TAG_INFO_CLASS = 9

    _OBJ_CASE_INSENSITIVE = 0x00000040
    _FILE_OPEN = 1
    _FILE_CREATE = 2
    _FILE_OPEN_IF = 3
    _FILE_DIRECTORY_FILE = 0x00000001
    _FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    _FILE_NON_DIRECTORY_FILE = 0x00000040
    _FILE_OPEN_REPARSE_POINT_NT = 0x00200000

    _STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034
    _STATUS_OBJECT_NAME_COLLISION = 0xC0000035
    _STATUS_OBJECT_PATH_NOT_FOUND = 0xC000003A

    class _FILE_ATTRIBUTE_TAG_INFO(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("ReparseTag", wintypes.DWORD),
        ]

    class _UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class _OBJECT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class _IO_STATUS_BLOCK(ctypes.Structure):
        _fields_ = [
            ("Status", wintypes.LONG),
            ("Information", ctypes.c_size_t),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _KERNEL32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _KERNEL32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL
    _GetFileInformationByHandleEx = _KERNEL32.GetFileInformationByHandleEx
    _GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _GetFileInformationByHandleEx.restype = wintypes.BOOL

    _NTDLL = ctypes.WinDLL("ntdll")
    _NtCreateFile = _NTDLL.NtCreateFile
    _NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_OBJECT_ATTRIBUTES),
        ctypes.POINTER(_IO_STATUS_BLOCK),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    _NtCreateFile.restype = wintypes.LONG
    _RtlNtStatusToDosError = _NTDLL.RtlNtStatusToDosError
    _RtlNtStatusToDosError.argtypes = [wintypes.LONG]
    _RtlNtStatusToDosError.restype = wintypes.ULONG


def _win_error(path: Path) -> OSError:
    import ctypes

    code = ctypes.get_last_error()
    return OSError(code, ctypes.FormatError(code), str(path))


def _win_error_code(error: OSError) -> int | None:
    """Prefer Win32 error when present; otherwise use Python errno."""
    winerror = getattr(error, "winerror", None)
    return error.errno if winerror is None else winerror


def _win_ntstatus_code(status: int) -> int:
    return int(status) & 0xFFFFFFFF


def _win_raise_ntstatus(status: int, label: str) -> None:
    if os.name != "nt":
        raise RuntimeError("FUGLE_DIAGNOSTIC_WINDOWS_API_UNAVAILABLE")
    code = int(_RtlNtStatusToDosError(status))
    raise OSError(code, ctypes.FormatError(code), label)


def _win_relative_create(
    parent_handle: int,
    name: str,
    *,
    desired_access: int,
    share_access: int,
    disposition: int,
    options: int,
    attributes: int = 0,
) -> tuple[int, int | None]:
    """NtCreateFile relative to an already-open directory handle."""
    if os.name != "nt":
        raise RuntimeError("FUGLE_DIAGNOSTIC_WINDOWS_API_UNAVAILABLE")
    encoded_length = len(name.encode("utf-16-le"))
    name_buffer = ctypes.create_unicode_buffer(name)
    unicode_name = _UNICODE_STRING(
        Length=encoded_length,
        MaximumLength=encoded_length + 2,
        Buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    object_attributes = _OBJECT_ATTRIBUTES(
        Length=ctypes.sizeof(_OBJECT_ATTRIBUTES),
        RootDirectory=wintypes.HANDLE(parent_handle),
        ObjectName=ctypes.pointer(unicode_name),
        Attributes=_OBJ_CASE_INSENSITIVE,
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    io_status = _IO_STATUS_BLOCK()
    handle = wintypes.HANDLE()
    status = int(_NtCreateFile(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(object_attributes),
        ctypes.byref(io_status),
        None,
        attributes,
        share_access,
        disposition,
        options,
        None,
        0,
    ))
    if status < 0:
        return status, None
    return status, int(handle.value)


def _win_close_handle(handle: int) -> None:
    if os.name != "nt":
        return
    if not _CloseHandle(handle):
        raise _win_error(Path("<handle>"))


def _win_check_directory_handle(handle: int) -> None:
    info = _FILE_ATTRIBUTE_TAG_INFO()
    if not _GetFileInformationByHandleEx(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _win_error(Path("<directory-handle>"))
    if not (info.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY):
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ANCESTRY_UNTRUSTED")
    if info.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ANCESTRY_UNTRUSTED")


def _win_open_directory(path: Path) -> int:
    """Open the trusted repository root without following a root reparse point."""
    if os.name != "nt":
        raise RuntimeError("FUGLE_DIAGNOSTIC_WINDOWS_API_UNAVAILABLE")
    handle = _CreateFileW(
        str(path),
        _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise _win_error(path)
    value = int(handle)
    try:
        _win_check_directory_handle(value)
    except Exception:
        _CloseHandle(handle)
        raise
    return value


def _win_open_or_create_child_directory(parent_handle: int, component: str) -> int:
    """Atomically open/create one child relative to its pinned parent handle."""
    status, handle = _win_relative_create(
        parent_handle,
        component,
        desired_access=_FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        disposition=_FILE_OPEN_IF,
        options=_FILE_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT_NT,
        attributes=_FILE_ATTRIBUTE_DIRECTORY,
    )
    if handle is None:
        _win_raise_ntstatus(status, component)
    try:
        _win_check_directory_handle(handle)
    except Exception:
        _win_close_handle(handle)
        raise
    return handle


def _win_require_target_absent(parent_handle: int, output_name: str) -> None:
    status, handle = _win_relative_create(
        parent_handle,
        output_name,
        desired_access=_FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        disposition=_FILE_OPEN,
        options=_FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT_NT,
    )
    if handle is not None:
        _win_close_handle(handle)
        raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_EXISTS")
    if _win_ntstatus_code(status) not in {
        _STATUS_OBJECT_NAME_NOT_FOUND,
        _STATUS_OBJECT_PATH_NOT_FOUND,
    }:
        try:
            _win_raise_ntstatus(status, output_name)
        except OSError as exc:
            raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_TARGET_UNTRUSTED") from exc


def _win_write_new(parent_handle: int, output_name: str, result: dict) -> None:
    status, handle = _win_relative_create(
        parent_handle,
        output_name,
        desired_access=_GENERIC_WRITE | _SYNCHRONIZE,
        share_access=0,
        disposition=_FILE_CREATE,
        options=_FILE_NON_DIRECTORY_FILE | _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT_NT,
        attributes=_FILE_ATTRIBUTE_NORMAL,
    )
    if handle is None:
        if _win_ntstatus_code(status) == _STATUS_OBJECT_NAME_COLLISION:
            raise FileExistsError(output_name)
        _win_raise_ntstatus(status, output_name)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
    except Exception:
        _win_close_handle(handle)
        raise
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _open_trusted_output_windows(output_name: str, root: Path, output_root: Path) -> _TrustedOutput:
    handles: list[int] = []
    try:
        try:
            root_handle = _win_open_directory(root)
        except OSError as exc:
            raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ROOT_UNAVAILABLE") from exc
        handles.append(root_handle)

        current_handle = root_handle
        for component in OUTPUT_PARTS:
            try:
                child_handle = _win_open_or_create_child_directory(current_handle, component)
            except (OSError, RuntimeError) as exc:
                raise RuntimeError("FUGLE_DIAGNOSTIC_OUTPUT_ANCESTRY_UNTRUSTED") from exc
            handles.append(child_handle)
            current_handle = child_handle

        # Target existence and final CREATE are both relative to this pinned handle.
        _win_require_target_absent(current_handle, output_name)
        return _TrustedOutput(output_name, output_root, windows_handles=handles)
    except Exception:
        for handle in reversed(handles):
            try:
                _win_close_handle(handle)
            except OSError:
                pass
        raise

def _open_trusted_output(output_name: str) -> _TrustedOutput:
    _validate_output_name(output_name)
    root, output_root = _validate_output_layout()
    if os.name == "nt":
        return _open_trusted_output_windows(output_name, root, output_root)
    return _open_trusted_output_posix(output_name, root, output_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True, choices=["09:30", "12:00"])
    parser.add_argument(
        "--output-name",
        required=True,
        help="New JSON basename under artifacts/diagnostics/fugle-free-intraday; existing files are rejected.",
    )
    args = parser.parse_args()

    # Pin and validate the full output directory chain before binding, credentials,
    # or network. Keep the same trusted directory object alive through persistence.
    with _open_trusted_output(args.output_name) as output:
        binding = _load_fixed_binding()
        token = os.getenv("FUGLE_API_KEY", "")
        result = qualify(
            token,
            binding,
            trading_date=args.trading_date,
            cadence=args.cadence,
            now_utc=datetime.now(timezone.utc),
        )
        output.write_result(result)

    print(json.dumps({
        key: result[key]
        for key in ("technical_validation_status", "market_coverage", "license_gate", "production_eligible")
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
