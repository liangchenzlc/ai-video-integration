"""Test-only process handles for the desktop's exact supervisor/API tree."""

import ctypes
import json
import sys
from ctypes import wintypes

import win32api
import win32event
import win32process


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def children() -> list[tuple[int, int, str]]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise RuntimeError("Process snapshot unavailable")
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    result = []
    try:
        valid = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            result.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            valid = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


def main() -> None:
    root = int(sys.argv[1])
    handles = {}
    try:
        handles["main"] = win32api.OpenProcess(0x100001, False, root)
        processes = children()
        parent = root
        ids = {"main": root}
        for role in ("supervisor", "api"):
            matches = [
                pid
                for pid, ppid, name in processes
                if ppid == parent and name.lower() in {"python.exe", "avi_backend.exe"}
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"Expected one owned backend process: {role}, parent={parent}"
                )
            parent = matches[0]
            handles[role] = win32api.OpenProcess(0x100001, False, parent)
            ids[role] = parent
        print(json.dumps({"ids": ids}), flush=True)
        for line in sys.stdin:
            command = json.loads(line)
            if command.get("kill") in handles:
                win32process.TerminateProcess(handles[command["kill"]], 93)
            alive = {
                role: win32event.WaitForSingleObject(handle, 0) == win32event.WAIT_TIMEOUT
                for role, handle in handles.items()
            }
            print(json.dumps({"alive": alive}), flush=True)
    finally:
        for handle in handles.values():
            handle.Close()


if __name__ == "__main__":
    main()
