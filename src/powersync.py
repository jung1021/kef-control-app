"""Turn the speakers on/off together with the PC.

Listens for Windows power/session events with a hidden window (no polling, no CPU use):
  sleep / hibernate, wake, shutdown / sign-out, lock / unlock, display off / on.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from ctypes import wintypes
from typing import Any, Callable

log = logging.getLogger("kefcontrol.power")

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "on_startup": True,      # PC starts / you sign in
    "on_wake": True,         # PC wakes from sleep
    "on_unlock": False,      # you unlock the PC
    "on_display": False,     # display turns back on
    "off_sleep": True,       # PC goes to sleep / hibernates
    "off_shutdown": True,    # PC shuts down / restarts / you sign out
    "off_lock": False,       # you lock the PC
    "off_display": False,    # display turns off
    "only_usb": True,        # only switch off if the speakers are playing from the PC (USB)
    "use_usb": True,         # switch to the USB input when turning on
}

LABELS = {
    "on_startup": "When the PC starts or I sign in",
    "on_wake": "When the PC wakes from sleep",
    "on_unlock": "When I unlock the PC",
    "on_display": "When the display turns on",
    "off_sleep": "When the PC goes to sleep",
    "off_shutdown": "When the PC shuts down or restarts",
    "off_lock": "When I lock the PC",
    "off_display": "When the display turns off",
    "only_usb": "Only switch off if the speakers are on the USB input",
    "use_usb": "Switch to the USB input when turning on",
}


def settings_from(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update({k: bool(v) for k, v in (cfg.get("power_sync") or {}).items() if k in DEFAULTS})
    return out


class PowerSync:
    """Decides what to do for each PC event. Platform independent (testable)."""

    def __init__(self, manager: Any, get_settings: Callable[[], dict[str, Any]]) -> None:
        self.m = manager
        self.get_settings = get_settings
        self._last: dict[str, float] = {}
        self._wake_gen = 0
        self.log: list[tuple[float, str, str]] = []  # (time, event, result) - last few, for the UI

    def _note(self, event: str, result: str) -> None:
        log.info("power event %s: %s", event, result)
        self.log = (self.log + [(time.time(), event, result)])[-8:]

    def _debounced(self, kind: str, seconds: float = 8.0) -> bool:
        now = time.monotonic()
        if now - self._last.get(kind, -1e9) < seconds:
            return True
        self._last[kind] = now
        return False

    # -- events ------------------------------------------------------------------
    def event(self, name: str) -> None:
        s = self.get_settings()
        if not s["enabled"] or self.m.client is None:
            return
        if name in ("startup", "wake", "unlock", "display_on"):
            key = {"startup": "on_startup", "wake": "on_wake", "unlock": "on_unlock",
                   "display_on": "on_display"}[name]
            if s[key] and not self._debounced("on"):
                self._last.pop("off", None)
                self._turn_on_async(name, s)
        elif name in ("sleep", "shutdown", "lock", "display_off"):
            key = {"sleep": "off_sleep", "shutdown": "off_shutdown", "lock": "off_lock",
                   "display_off": "off_display"}[name]
            if s[key] and not self._debounced("off", 3.0):
                self._last.pop("on", None)  # a wake right after this must not be ignored
                self._turn_off(name, s)  # synchronous: Windows may suspend right after we return

    def _turn_off(self, name: str, s: dict[str, Any]) -> None:
        self._wake_gen += 1  # cancel any pending wake retries
        try:
            src = self.m.run(lambda c: c.get_source()).value
            if src == "standby":
                self._note(name, "already in standby")
                return
            if s["only_usb"]:
                if src != "usb":
                    self._note(name, f"left on (input is {src})")
                    return
            self.m.power(False)
            self._note(name, "standby")
        except Exception as err:  # noqa: BLE001
            self._note(name, f"failed: {err}")

    def _turn_on_async(self, name: str, s: dict[str, Any]) -> None:
        self._wake_gen += 1
        gen = self._wake_gen

        def work() -> None:
            # Right after wake-up the network may not be ready yet: retry for ~60 s.
            deadline = time.monotonic() + 60
            delay = 1.5
            while gen == self._wake_gen:
                try:
                    st = self.m.state()
                    if st.get("connected"):
                        if st.get("on"):
                            self._note(name, "already on")
                        else:
                            self.m.power(True, "usb" if s["use_usb"] else None)
                            self._note(name, "turned on")
                        return
                except Exception as err:  # noqa: BLE001
                    log.debug("wake attempt failed: %s", err)
                if time.monotonic() > deadline:
                    self._note(name, "speaker not reachable")
                    return
                time.sleep(delay)
                delay = min(delay * 1.5, 8)

        threading.Thread(target=work, daemon=True, name="kef-wake").start()


# --------------------------------------------------------------------------- #
# Windows event listener
# --------------------------------------------------------------------------- #

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0
DEVICE_NOTIFY_WINDOW_HANDLE = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


# GUID_CONSOLE_DISPLAY_STATE {6FE69556-704A-47A0-8F24-C28D936FDA47}
GUID_CONSOLE_DISPLAY_STATE = GUID(0x6FE69556, 0x704A, 0x47A0,
                                  (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47))


class POWERBROADCAST_SETTING(ctypes.Structure):  # noqa: N801
    _fields_ = [("PowerSetting", GUID), ("DataLength", wintypes.DWORD), ("Data", ctypes.c_ubyte * 4)]


class WindowsListener:
    """Hidden top-level window that receives power/session broadcasts."""

    def __init__(self, on_event: Callable[[str], None]) -> None:
        self.on_event = on_event
        self.hwnd = None
        self._thread: threading.Thread | None = None
        self._display_on: bool | None = None

    def start(self) -> None:
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="kef-power-events")
        self._thread.start()

    def _dispatch(self, name: str, sync: bool) -> None:
        if sync:
            try:
                self.on_event(name)
            except Exception:  # noqa: BLE001
                log.debug("event handler failed", exc_info=True)
        else:
            threading.Thread(target=self.on_event, args=(name,), daemon=True).start()

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

        LRESULT = ctypes.c_ssize_t  # noqa: N806
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)  # noqa: N806

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                        ("hIconSm", wintypes.HICON)]

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD]
        user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
        wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        def wndproc(hwnd, msg, wparam, lparam):  # noqa: ANN001, ANN202
            try:
                if msg == WM_POWERBROADCAST:
                    if wparam == PBT_APMSUSPEND:
                        self._dispatch("sleep", sync=True)
                    elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                        self._dispatch("wake", sync=False)
                    elif wparam == PBT_POWERSETTINGCHANGE and lparam:
                        pbs = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
                        state = pbs.Data[0]  # 0 off, 1 on, 2 dimmed
                        on = state != 0
                        if self._display_on is not None and on != self._display_on:
                            self._dispatch("display_on" if on else "display_off", sync=not on)
                        self._display_on = on
                    return 1
                if msg == WM_WTSSESSION_CHANGE:
                    if wparam == WTS_SESSION_LOCK:
                        self._dispatch("lock", sync=False)
                    elif wparam == WTS_SESSION_UNLOCK:
                        self._dispatch("unlock", sync=False)
                    return 0
                if msg == WM_QUERYENDSESSION:
                    return 1
                if msg == WM_ENDSESSION:
                    if wparam:
                        self._dispatch("shutdown", sync=True)
                    return 0
            except Exception:  # noqa: BLE001
                log.debug("wndproc error", exc_info=True)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)  # keep a reference
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "KEFControlPowerEvents"
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            log.warning("RegisterClassEx failed: %s", ctypes.get_last_error())
            return
        # A hidden *top-level* window (message-only windows don't get power broadcasts).
        hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "KEF Control power events", 0,
                                      0, 0, 0, 0, None, None, hinst, None)
        if not hwnd:
            log.warning("CreateWindowEx failed: %s", ctypes.get_last_error())
            return
        self.hwnd = hwnd
        try:
            wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)
        except Exception:  # noqa: BLE001
            log.debug("WTSRegisterSessionNotification failed", exc_info=True)
        try:
            user32.RegisterPowerSettingNotification(hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE),
                                                    DEVICE_NOTIFY_WINDOW_HANDLE)
        except Exception:  # noqa: BLE001
            log.debug("RegisterPowerSettingNotification failed", exc_info=True)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
