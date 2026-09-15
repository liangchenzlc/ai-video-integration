"""The API process holds one per-user mutex, acquired and released on its main thread."""

from __future__ import annotations

from typing import Any

import win32api
import win32con
import win32event
import win32security


class BackendAlreadyRunning(Exception):
    pass


class ApiMutex:
    def __init__(self) -> None:
        self._handle: Any = None

    def __enter__(self) -> ApiMutex:
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            name = "Local\\AIVideoIntegration.Api." + win32security.ConvertSidToStringSid(sid)
        finally:
            token.Close()
        handle = win32event.CreateMutex(None, False, name)
        try:
            win32api.SetHandleInformation(handle, win32con.HANDLE_FLAG_INHERIT, 0)
            result = win32event.WaitForSingleObject(handle, 0)
            if result == win32event.WAIT_TIMEOUT:
                raise BackendAlreadyRunning()
            if result not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
                raise RuntimeError("Unable to acquire API mutex")
            self._handle = handle
            return self
        except BaseException:
            handle.Close()
            raise

    def __exit__(self, *_: object) -> None:
        if self._handle is not None:
            try:
                win32event.ReleaseMutex(self._handle)
            finally:
                self._handle.Close()
                self._handle = None
