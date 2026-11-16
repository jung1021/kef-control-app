"""System-tray icon for KEF Control.

The tray process is idle almost all of the time: it never polls the speaker.
It refreshes the speaker state only when you right-click the icon or use a menu item.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pystray
from PIL import Image

log = logging.getLogger("kefcontrol.tray")

SOURCE_LABELS = {
    "usb": "USB", "optical": "Optical", "tv": "TV", "bluetooth": "Bluetooth",
    "wifi": "Wi-Fi", "analog": "Analogue", "coaxial": "Coaxial",
}
SOURCE_ORDER = ["usb", "optical", "tv", "bluetooth", "wifi", "analog", "coaxial"]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "KEF Control"


# --------------------------------------------------------------------------- #
# Start with Windows (HKCU Run key - no admin rights needed)
# --------------------------------------------------------------------------- #


def _launch_command(script: Path) -> str:
    launcher = os.environ.get("KEFCONTROL_EXE")
    if launcher and Path(launcher).exists():  # installed version: KEFControl.exe
        return f'"{launcher}" --background'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    if pyw.exists():
        exe = pyw
    return f'"{exe}" "{script}" --background'


def _packaged() -> bool:
    """True when running from the Microsoft Store (MSIX) package."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        length = ctypes.c_uint32(0)
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700
    except Exception:  # noqa: BLE001
        return False


def autostart_enabled() -> bool:
    if sys.platform != "win32" or _packaged():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool, script: Path) -> None:
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _launch_command(script))
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Tray icon
# --------------------------------------------------------------------------- #


def _icon_class() -> type:
    """pystray only builds its menu when told to; refresh state right before it pops up."""
    base = pystray.Icon
    if sys.platform != "win32":
        return base

    from pystray._util import win32  # type: ignore[attr-defined]

    class RefreshingIcon(base):  # type: ignore[misc, valid-type]
        before_menu: Callable[[], None] | None = None

        def _on_notify(self, wparam, lparam):  # noqa: ANN001
            if lparam == win32.WM_RBUTTONUP and self.before_menu is not None:
                try:
                    self.before_menu()
                except Exception:  # noqa: BLE001
                    log.debug("menu refresh failed", exc_info=True)
            return super()._on_notify(wparam, lparam)

    return RefreshingIcon


class Tray:
    def __init__(self, manager: Any, open_window: Callable[[], None], quit_app: Callable[[], None],
                 icon_path: Path, script: Path) -> None:
        self.m = manager
        self.open_window = open_window
        self.quit_app = quit_app
        self.script = script
        self.state: dict[str, Any] = {}
        self._lock = threading.Lock()

        image = Image.open(icon_path)
        image.load()
        cls = _icon_class()
        self.icon = cls("KEFControl", image, "KEF Control", menu=self._menu())
        if hasattr(self.icon, "before_menu"):
            self.icon.before_menu = self._refresh_for_menu

    # -- state -------------------------------------------------------------------
    def _refresh(self) -> None:
        with self._lock:
            try:
                st = self.m.state()
            except Exception as err:  # noqa: BLE001
                st = {"configured": True, "connected": False, "error": str(err)}
            self.state = st
        self._update_title()

    def _redraw_menu(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("menu redraw failed", exc_info=True)

    def _refresh_for_menu(self) -> None:
        # Fetch fresh state, but never keep the menu waiting more than ~0.8 s.
        t = threading.Thread(target=self._refresh, daemon=True)
        t.start()
        t.join(0.8)
        self._redraw_menu()

    def _update_title(self) -> None:
        # The hover tooltip is intentionally fixed: it can't refresh itself without
        # polling the speaker, and stale status text is worse than none. Live status
        # is shown at the top of the right-click menu, which refreshes when it opens.
        pass

    # -- actions -----------------------------------------------------------------
    def _do(self, fn: Callable[[], Any]) -> Callable[..., None]:
        def run(*_: Any) -> None:
            def work() -> None:
                try:
                    fn()
                except Exception as err:  # noqa: BLE001
                    log.debug("tray action failed", exc_info=True)
                    try:
                        self.icon.notify(str(err) or "Action failed", "KEF Control")
                    except Exception:  # noqa: BLE001
                        pass
                self._refresh()
                self._redraw_menu()
            threading.Thread(target=work, daemon=True).start()
        return run

    def _connected(self) -> bool:
        return bool(self.state.get("connected"))

    def _menu(self) -> pystray.Menu:
        I = pystray.MenuItem  # noqa: N806

        def src_item(src: str) -> pystray.MenuItem:
            return I(SOURCE_LABELS[src], self._do(lambda: self.m.set_source(src)),
                     checked=lambda _: bool(self.state.get("on")) and self.state.get("source") == src,
                     radio=True,
                     visible=lambda _: src in ((self.state.get("info") or {}).get("sources") or SOURCE_ORDER[:5]))

        return pystray.Menu(
            I("Open KEF Control", lambda *_: self.open_window(), default=True),
            I(lambda _: f"Update available: v{(self._update() or {}).get('version', '')}",
              self._open_update, visible=lambda _: bool(self._update())),
            pystray.Menu.SEPARATOR,
            I(lambda _: self._status_text(), None, enabled=False),
            I(lambda _: "Standby" if self.state.get("on") else "Turn on",
              self._do(lambda: self.m.power(not self.state.get("on"))), enabled=lambda _: self._connected()),
            I("Mute", self._do(lambda: self.m.set_mute(not self.state.get("muted"))),
              checked=lambda _: bool(self.state.get("muted")), enabled=lambda _: self._connected()),
            I("Volume up", self._do(lambda: self.m.step_volume(+1)), enabled=lambda _: self._connected()),
            I("Volume down", self._do(lambda: self.m.step_volume(-1)), enabled=lambda _: self._connected()),
            I("Source", pystray.Menu(*[src_item(s) for s in SOURCE_ORDER]), enabled=lambda _: self._connected()),
            I("Play / Pause", self._do(lambda: self.m.playback("playpause")),
              visible=lambda _: self._streaming()),
            I("Next track", self._do(lambda: self.m.playback("next")), visible=lambda _: self._streaming()),
            I("Sound profile", pystray.Menu(self._profile_items),
              enabled=lambda _: self._connected() and bool(self.m.cfg.get("profiles")),
              visible=lambda _: bool(self.m.cfg.get("profiles"))),
            I("Speakers", pystray.Menu(self._speaker_items),
              visible=lambda _: len(self.m.cfg.get("speakers") or []) > 1),
            pystray.Menu.SEPARATOR,
            I("Start with Windows", self._toggle_autostart, checked=lambda _: autostart_enabled(),
              visible=sys.platform == "win32" and not _packaged()),
            # Store version: start-up is a Windows "startup app" managed in Settings.
            I("Startup settings…", lambda *_: os.startfile("ms-settings:startupapps"),
              visible=sys.platform == "win32" and _packaged()),
            I("Quit", self._quit),
        )

    def _profile_items(self) -> tuple:  # rebuilt each time the menu is drawn
        items = []
        for prof in self.m.cfg.get("profiles") or []:
            name = prof["name"]
            items.append(pystray.MenuItem(
                name, self._do(lambda n=name: self.m.apply_profile(n)),
                checked=lambda _, n=name: self.m.cfg.get("active_profile") == n, radio=True))
        return tuple(items)

    def _streaming(self) -> bool:
        return self._connected() and bool(self.state.get("on")) and self.state.get("source") in ("wifi", "bluetooth")

    def _update(self) -> dict | None:
        return self.state.get("update")

    def _open_update(self, *_: Any) -> None:
        import webbrowser
        u = self._update()
        if u and u.get("url"):
            webbrowser.open(u["url"])

    def _speaker_items(self) -> tuple:
        items = []
        cur = self.m._current_id()
        for sp in self.m.cfg.get("speakers") or []:
            sid = sp["id"]
            label = sp.get("name") or sp.get("host")
            items.append(pystray.MenuItem(
                label, self._do(lambda i=sid: self.m.switch_speaker(i)),
                checked=lambda _, i=sid: self.m._current_id() == i, radio=True))
        del cur
        return tuple(items)

    def _status_text(self) -> str:
        s = self.state
        if not s:
            return "KEF Control"
        if not s.get("configured"):
            return "No speaker set up"
        if not s.get("connected"):
            return "Speaker offline"
        name = ((s.get("info") or {}).get("device") or {}).get("name") or "KEF"
        if not s.get("on"):
            return f"{name}: standby"
        p = s.get("playing") or {}
        track = f" · {p['title'][:40]}" if p.get("title") else ""
        return f"{name}: {SOURCE_LABELS.get(s.get('source'), s.get('source'))} · vol {s.get('volume')}{track}"

    def _toggle_autostart(self, *_: Any) -> None:
        try:
            set_autostart(not autostart_enabled(), self.script)
        except OSError as err:
            self.icon.notify(f"Couldn't change startup setting: {err}", "KEF Control")
        self._redraw_menu()

    def _quit(self, *_: Any) -> None:
        self.quit()

    def quit(self) -> None:
        # Make sure the process really ends (so an installer/uninstaller can replace its files),
        # even if the tray message loop is slow to stop.
        threading.Thread(target=lambda: (time.sleep(2.0), os._exit(0)), daemon=True).start()
        try:
            self.icon.stop()
        finally:
            self.quit_app()

    # -- run -----------------------------------------------------------------------
    def run(self) -> None:
        def setup(icon: pystray.Icon) -> None:
            icon.visible = True
            self._refresh()
            self._redraw_menu()
        self.icon.run(setup=setup)
