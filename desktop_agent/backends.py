from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
import ctypes
import ctypes.wintypes
import subprocess
import time

from PIL import ImageGrab


@dataclass
class ControlInfo:
    handle: int
    text: str
    class_name: str
    rect: tuple[int, int, int, int]


@dataclass
class WindowInfo:
    handle: int
    title: str
    class_name: str
    rect: tuple[int, int, int, int]
    controls: list[ControlInfo] = field(default_factory=list)


class DesktopBackend(Protocol):
    def launch(self, command: list[str], cwd: str | None = None) -> int: ...
    def windows(self) -> list[WindowInfo]: ...
    def focus_window(self, handle: int) -> None: ...
    def click(self, x: int, y: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def screenshot(self, path: str | Path) -> None: ...
    def close_window(self, handle: int) -> None: ...


class Win32DesktopBackend:
    """Small Win32 backend with no UIA dependency.

    It observes top-level windows and child HWNDs, captures screenshots with Pillow,
    and delivers mouse/keyboard input through SendInput. It is intentionally generic:
    testcase artifacts decide which windows, controls, and assertions matter.
    """

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32

    def launch(self, command: list[str], cwd: str | None = None) -> int:
        proc = subprocess.Popen(command, cwd=cwd)
        return proc.pid

    def windows(self) -> list[WindowInfo]:
        result: list[WindowInfo] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            title = self._text(hwnd)
            if not title:
                return True
            result.append(WindowInfo(hwnd, title, self._class_name(hwnd), self._rect(hwnd), self._children(hwnd)))
            return True

        self.user32.EnumWindows(enum_proc, 0)
        return result

    def focus_window(self, handle: int) -> None:
        self.user32.ShowWindow(handle, 5)
        self.user32.SetForegroundWindow(handle)
        time.sleep(0.15)

    def click(self, x: int, y: int) -> None:
        self.user32.SetCursorPos(x, y)
        time.sleep(0.05)
        self.user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.03)
        self.user32.mouse_event(0x0004, 0, 0, 0, 0)

    def type_text(self, text: str) -> None:
        for ch in text:
            try:
                self._send_unicode(ch)
            except OSError:
                self._post_char(ch)
            time.sleep(0.01)

    def screenshot(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab().save(path)

    def close_window(self, handle: int) -> None:
        self.user32.PostMessageW(handle, 0x0010, 0, 0)

    def _children(self, hwnd: int) -> list[ControlInfo]:
        children: list[ControlInfo] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_child(child: int, _lparam: int) -> bool:
            if self.user32.IsWindowVisible(child):
                children.append(ControlInfo(child, self._text(child), self._class_name(child), self._rect(child)))
            return True

        self.user32.EnumChildWindows(hwnd, enum_child, 0)
        return children

    def _text(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value

    def _class_name(self, hwnd: int) -> str:
        buff = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buff, 256)
        return buff.value

    def _rect(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = ctypes.wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return (rect.left, rect.top, rect.right, rect.bottom)

    def _send_unicode(self, ch: str) -> None:
        ulong_ptr = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.wintypes.DWORD), ("union", INPUTUNION)]

        down = INPUT(1, INPUTUNION(KEYBDINPUT(0, ord(ch), 0x0004, 0, 0)))
        up = INPUT(1, INPUTUNION(KEYBDINPUT(0, ord(ch), 0x0004 | 0x0002, 0, 0)))
        sent_down = self.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        sent_up = self.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
        if sent_down != 1 or sent_up != 1:
            raise OSError("SendInput failed while delivering Unicode text.")

    def _post_char(self, ch: str) -> None:
        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("flags", ctypes.wintypes.DWORD),
                ("hwndActive", ctypes.wintypes.HWND),
                ("hwndFocus", ctypes.wintypes.HWND),
                ("hwndCapture", ctypes.wintypes.HWND),
                ("hwndMenuOwner", ctypes.wintypes.HWND),
                ("hwndMoveSize", ctypes.wintypes.HWND),
                ("hwndCaret", ctypes.wintypes.HWND),
                ("rcCaret", ctypes.wintypes.RECT),
            ]

        foreground = self.user32.GetForegroundWindow()
        thread_id = self.user32.GetWindowThreadProcessId(foreground, None)
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        target = foreground
        if self.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.hwndFocus:
            target = info.hwndFocus
        if not self.user32.PostMessageW(target, 0x0102, ord(ch), 1):
            raise OSError("WM_CHAR fallback failed while delivering text.")


class MemoryDesktopBackend:
    """Deterministic backend for testing the coordinator without touching the desktop."""

    def __init__(self, windows: list[WindowInfo] | None = None) -> None:
        self._windows = windows or []
        self.actions: list[tuple[str, object]] = []
        self.closed: list[int] = []

    def launch(self, command: list[str], cwd: str | None = None) -> int:
        self.actions.append(("launch", command))
        return 1

    def windows(self) -> list[WindowInfo]:
        return self._windows

    def focus_window(self, handle: int) -> None:
        self.actions.append(("focus", handle))

    def click(self, x: int, y: int) -> None:
        self.actions.append(("click", (x, y)))

    def type_text(self, text: str) -> None:
        self.actions.append(("type", text))

    def screenshot(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"memory screenshot placeholder")

    def close_window(self, handle: int) -> None:
        self.closed.append(handle)
        self.actions.append(("close", handle))
