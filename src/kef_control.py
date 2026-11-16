"""KEF Control - a desktop replacement for the KEF Connect app (LSX II / LSX II LT and other W2 speakers).

Runs a tiny web server on 127.0.0.1 and opens the UI in a chromeless Edge/Chrome
"app" window. All speaker communication goes through the open-source
pykefcontrol library, over your local network (the same way KEF Connect does).

Usage:
    pythonw kef_control.py            # normal start (no console)
    python  kef_control.py --debug    # with console logging
    python  kef_control.py --no-window   # only run the server, open http://127.0.0.1:47801 yourself
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

try:
    from pykefcontrol import KefClient
    from pykefcontrol.capabilities import Feature
    from pykefcontrol.enums import (
        BassExtension,
        KefEnum,
        MasterChannelMode,
        Polarity,
        SoundProfile,
        Source,
        StandbyMode,
        SubwooferPreset,
        WakeUpSource,
    )
    from pykefcontrol.settings import Settings
except ImportError:  # pragma: no cover
    print("pykefcontrol is not installed. Run install.bat (or: pip install \"pykefcontrol[discovery]\")")
    raise

APP_NAME = "KEF Control"
APP_VERSION = "1.3.2"
GITHUB_REPO = "jung1021/kef-control-app"
UPDATE_CHECK_INTERVAL = 24 * 3600
def _is_packaged() -> bool:
    """True when running from the Microsoft Store (MSIX) package."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        length = ctypes.c_uint32(0)
        rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
        return rc != 15700  # APPMODEL_ERROR_NO_PACKAGE
    except Exception:  # noqa: BLE001
        return False


IS_PACKAGED = _is_packaged()
REDISCOVER_INTERVAL = 45.0  # seconds between network scans while the speaker is unreachable
PORT = 47801
HERE = Path(__file__).resolve().parent
UI_FILE = HERE / "ui.html"

log = logging.getLogger("kefcontrol")

# Last few warnings/errors, shown in "Copy diagnostics" (no personal data is logged).
import collections  # noqa: E402

RECENT_ERRORS: collections.deque = collections.deque(maxlen=20)


class _RecentErrors(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            RECENT_ERRORS.append((time.strftime("%H:%M:%S"), f"{record.levelname} {record.getMessage()}"[:300]))
        except Exception:  # noqa: BLE001
            pass


_h = _RecentErrors(logging.WARNING)
logging.getLogger().addHandler(_h)


# --------------------------------------------------------------------------- #
# Update check (GitHub releases) - at startup and once a day, can be turned off
# --------------------------------------------------------------------------- #


def _ver(s: str) -> tuple[int, ...]:
    out = []
    for part in s.strip().lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


class UpdateChecker:
    def __init__(self, enabled: Callable[[], bool]) -> None:
        self.enabled = enabled
        self.latest: dict[str, Any] | None = None
        self.checked_at: float | None = None
        self.error: str | None = None

    def check(self) -> dict[str, Any] | None:
        import ssl
        import urllib.request
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": f"KEFControl/{APP_VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as r:
                data = json.loads(r.read().decode("utf-8"))
            tag = str(data.get("tag_name") or "")
            self.checked_at = time.time()
            self.error = None
            if tag and _ver(tag) > _ver(APP_VERSION):
                self.latest = {"version": tag.lstrip("vV"), "url": data.get("html_url"),
                               "notes": (data.get("body") or "")[:2000]}
            else:
                self.latest = None
        except Exception as err:  # noqa: BLE001 - offline etc.
            self.error = str(err)
            log.debug("update check failed: %s", err)
        return self.latest

    def loop(self) -> None:
        time.sleep(20)  # don't slow down start-up
        while True:
            if self.enabled():
                self.check()
            time.sleep(UPDATE_CHECK_INTERVAL)

    def start(self) -> None:
        threading.Thread(target=self.loop, daemon=True, name="kef-update-check").start()


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "KEFControl"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_FILE = config_dir() / "config.json"


def load_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict[str, Any]) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), "utf-8")
    except OSError as err:
        log.warning("Could not save config: %s", err)


# --------------------------------------------------------------------------- #
# Speaker settings shown in the UI
# --------------------------------------------------------------------------- #

# key -> (Setting, label, group, help, feature-gate or None, extra)
SETTING_DEFS: list[dict[str, Any]] = [
    # Power
    dict(key="standby_mode", setting=Settings.STANDBY_MODE, group="Power", label="Auto standby",
         choices=[("standby_20mins", "After 20 minutes"), ("standby_30mins", "After 30 minutes"),
                  ("standby_60mins", "After 60 minutes"), ("standby_none", "Never")]),
    dict(key="wake_up_source", setting=Settings.WAKE_UP_SOURCE, group="Power", label="Wake-up source",
         help="Which input wakes the speakers up when it receives a signal.",
         choices=[("wakeup_default", "Default"), ("usb", "USB"), ("optical", "Optical"),
                  ("tv", "TV (HDMI eARC)"), ("bluetooth", "Bluetooth"), ("analog", "Analogue"),
                  ("coaxial", "Coaxial")]),
    dict(key="auto_switch_to_tv", setting=Settings.AUTO_SWITCH_TO_TV, group="Power",
         label="Auto-switch to TV", feature=Feature.AUTO_SWITCH_TV,
         help="Switch to the TV input automatically when the TV turns on."),
    dict(key="startup_tone", setting=Settings.STARTUP_TONE, group="Power", label="Startup tone",
         feature=Feature.STARTUP_TONE),
    # Volume
    dict(key="volume_limit", setting=Settings.VOLUME_LIMIT, group="Volume", label="Limit maximum volume"),
    dict(key="maximum_volume", setting=Settings.MAXIMUM_VOLUME, group="Volume", label="Maximum volume",
         min=0, max=100, step=1),
    dict(key="volume_step", setting=Settings.VOLUME_STEP, group="Volume", label="Volume step",
         min=1, max=10, step=1, help="Step used by the remote / top panel and by the +/- buttons."),
    dict(key="standby_default_volume", setting=Settings.STANDBY_DEFAULT_VOLUME, group="Volume",
         label="Reset volume after standby",
         help="When the speakers wake up, start at the default volume instead of the last one."),
    # Lights & hardware
    dict(key="disable_front_led", setting=Settings.DISABLE_FRONT_LED, group="Lights & hardware",
         label="Front LED off"),
    dict(key="disable_front_standby_led", setting=Settings.DISABLE_FRONT_STANDBY_LED,
         group="Lights & hardware", label="Standby LED off", feature=Feature.STANDBY_FRONT_LED),
    dict(key="usb_charging", setting=Settings.USB_CHARGING, group="Lights & hardware",
         label="USB charging", feature=Feature.USB_CHARGING),
    dict(key="master_channel_mode", setting=Settings.MASTER_CHANNEL_MODE, group="Lights & hardware",
         label="Primary speaker is the", choices=[("left", "Left speaker"), ("right", "Right speaker")]),
    dict(key="subwoofer_force_on", setting=Settings.SUBWOOFER_FORCE_ON, group="Lights & hardware",
         label="Keep subwoofer awake", feature=Feature.SUBWOOFER_FORCE_ON),
    dict(key="device_name", setting=Settings.DEVICE_NAME, group="Lights & hardware", label="Speaker name",
         text=True),
]

ENUM_FIELDS = {
    "bass_extension": BassExtension,
    "subwoofer_polarity": Polarity,
    "audio_polarity": Polarity,
    "subwoofer_preset": SubwooferPreset,
    "sound_profile": SoundProfile,
}
BOOL_FIELDS = {"desk_mode", "wall_mode", "phase_correction", "high_pass_mode", "subwoofer_out",
               "sub_stereo", "expert_mode", "wall_mounted"}
INT_FIELDS = {"balance", "subwoofer_count"}
FLOAT_FIELDS = {"desk_mode_setting", "wall_mode_setting", "treble", "high_pass_freq",
                "sub_out_low_pass_freq", "subwoofer_gain"}
EDITABLE_EQ = BOOL_FIELDS | INT_FIELDS | FLOAT_FIELDS | set(ENUM_FIELDS) - {"sound_profile"}
# What a sound profile stores (the speaker's own tone & placement settings).
PROFILE_KEYS = ["desk_mode", "desk_mode_setting", "wall_mode", "wall_mode_setting", "treble",
                "bass_extension", "balance", "phase_correction", "subwoofer_gain"]


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def jsonable(value: Any) -> Any:
    if isinstance(value, KefEnum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# --------------------------------------------------------------------------- #
# Speaker manager
# --------------------------------------------------------------------------- #


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class SpeakerManager:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.client: KefClient | None = None
        self.lock = threading.RLock()
        self.info: dict[str, Any] = {}
        self.capabilities = None
        self.last_error: str | None = None
        self._last_discovery = -1e9
        self.reconnected_at: float | None = None
        self._migrate_speakers()
        host = self.cfg.get("host")
        if host:
            self._open(host)

    # -- connection ------------------------------------------------------------
    def _open(self, host: str) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # noqa: BLE001
                pass
        self.client = KefClient(host, timeout=6.0)
        self.info = {}
        self.capabilities = None

    def connect(self, host: str) -> dict[str, Any]:
        host = host.strip()
        if not host:
            raise ApiError("Enter the speaker's IP address.")
        with self.lock:
            previous = self.cfg.get("host")
            self._open(host)
            try:
                self._load_info()
            except Exception as err:  # noqa: BLE001
                self.last_error = str(err)
                if previous and previous != host:
                    self._open(previous)  # keep using the speaker we had
                raise ApiError(f"Could not reach a KEF speaker at {host}: {err}", 502) from err
            self.cfg["host"] = host
            self._remember_current()
            save_config(self.cfg)
        return self.info

    def forget(self) -> None:
        """Remove the current speaker; switch to another saved one if there is one."""
        with self.lock:
            cur = self._current_id()
            self.cfg["speakers"] = [sp for sp in self.cfg.get("speakers", []) if sp["id"] != cur]
            if self.client:
                self.client.close()
            self.client = None
            self.info = {}
            for k in ("host", "mac", "name"):
                self.cfg.pop(k, None)
            rest = self.cfg["speakers"]
            if rest:
                self._select(rest[0])
            save_config(self.cfg)

    # -- multiple speakers ---------------------------------------------------------
    def _migrate_speakers(self) -> None:
        if "speakers" not in self.cfg:
            self.cfg["speakers"] = []
            if self.cfg.get("host"):
                self.cfg["speakers"].append({
                    "id": self.cfg.get("mac") or self.cfg["host"], "host": self.cfg["host"],
                    "mac": self.cfg.get("mac"), "name": self.cfg.get("name"), "model": None})
            save_config(self.cfg)

    def _current_id(self) -> str | None:
        return self.cfg.get("mac") or self.cfg.get("host")

    def _remember_current(self) -> None:
        """Add/update the connected speaker in the saved list (keyed by MAC, else host)."""
        host, mac = self.cfg.get("host"), self.cfg.get("mac")
        if not host:
            return
        items = self.cfg.setdefault("speakers", [])
        rec = next((sp for sp in items if (mac and sp.get("mac") == mac) or sp.get("host") == host
                    or sp["id"] == host), None)
        if rec is None:
            rec = {}
            items.append(rec)
        rec.update({"id": mac or host, "host": host, "mac": mac, "name": self.cfg.get("name"),
                    "model": (self.info or {}).get("model") or rec.get("model")})

    def _select(self, rec: dict[str, Any]) -> None:
        self.cfg["host"] = rec["host"]
        for k in ("mac", "name"):
            if rec.get(k):
                self.cfg[k] = rec[k]
            else:
                self.cfg.pop(k, None)
        self._open(rec["host"])

    def speakers(self) -> dict[str, Any]:
        cur = self._current_id()
        return {"speakers": [dict(sp, current=sp["id"] == cur) for sp in self.cfg.get("speakers", [])],
                "current": cur}

    def switch_speaker(self, sid: str) -> dict[str, Any]:
        with self.lock:
            rec = next((sp for sp in self.cfg.get("speakers", []) if sp["id"] == sid), None)
            if rec is None:
                raise ApiError("That speaker isn't saved any more.", 404)
            self._select(rec)
            save_config(self.cfg)
        return self.speakers()

    def remove_speaker(self, sid: str) -> dict[str, Any]:
        with self.lock:
            if sid == self._current_id():
                self.forget()
            else:
                self.cfg["speakers"] = [sp for sp in self.cfg.get("speakers", []) if sp["id"] != sid]
                save_config(self.cfg)
        return self.speakers()

    def _need(self) -> KefClient:
        if self.client is None:
            raise ApiError("No speaker configured.", 409)
        return self.client

    # -- auto-reconnect ------------------------------------------------------------
    def _rediscover(self) -> bool:
        """The speaker didn't answer: look for it on the network (its IP may have changed).

        Matches on the MAC address remembered from the last successful connection.
        Rate-limited so an unplugged speaker doesn't cause constant network scans.
        """
        now = time.monotonic()
        if now - self._last_discovery < REDISCOVER_INTERVAL:
            return False
        self._last_discovery = now
        mac = self.cfg.get("mac")
        name = self.cfg.get("name")
        try:
            found = discover_raw(3.0)
        except Exception as err:  # noqa: BLE001 - zeroconf missing / network down
            log.debug("rediscovery failed: %s", err)
            return False
        match = None
        if mac:
            match = next((sp for sp in found if norm_mac(sp.mac_address) == mac), None)
        if match is None and not mac and name:
            same = [sp for sp in found if sp.name == name]
            match = same[0] if len(same) == 1 else None
        current = self.client.host if self.client else None
        if match is None or match.host == current:
            return False
        log.info("Speaker moved from %s to %s", current, match.host)
        self._open(match.host)
        self.cfg["host"] = match.host
        self._remember_current()
        save_config(self.cfg)
        self.reconnected_at = time.time()
        return True

    def run(self, fn: Callable[[KefClient], Any]) -> Any:
        """Run fn(client); if the speaker can't be reached, try to find it again and retry once."""
        with self.lock:
            c = self._need()
            try:
                return fn(c)
            except (ApiError, ValueError, TypeError):
                raise
            except Exception:  # noqa: BLE001 - connection problems
                if self._rediscover():
                    return fn(self._need())
                raise

    def _load_info(self) -> None:
        c = self._need()
        di = c.get_device_info()
        caps = c.get_capabilities()
        self.capabilities = caps
        self.info = {
            "host": c.host,
            "secure": c.is_secure,
            "device": jsonable(di),
            "model": jsonable(caps.model),
            "firmware": str(caps.firmware) if caps.firmware else None,
            "sources": [s.value for s in caps.sources],
        }
        mac = norm_mac(di.mac_address)
        if self.cfg.get("host") != c.host:
            # Switched to a different speaker: forget the previous one's identity.
            self.cfg["host"] = c.host
            self.cfg.pop("mac", None)
            self.cfg.pop("name", None)
        if mac:
            self.cfg["mac"] = mac
        if di.name:
            self.cfg["name"] = di.name
        self._remember_current()
        save_config(self.cfg)

    # -- state -----------------------------------------------------------------
    def state(self) -> dict[str, Any]:
        if self.client is None:
            return {"configured": False}

        def read(c: KefClient) -> dict[str, Any]:
            if not self.info:
                self._load_info()
            source = c.get_source()
            status = c.get_status()
            volume = c.get_volume()
            try:
                muted = c.get_mute()
            except Exception:  # noqa: BLE001
                muted = None
            playing = None
            if source.value in ("wifi", "bluetooth"):
                playing = self._now_playing(c)
            return {
                "configured": True,
                "connected": True,
                "info": self.info,
                "playing": playing,
                "source": source.value,
                "status": status.value,
                "on": source != Source.STANDBY and status.value != "standby",
                "volume": volume,
                "muted": muted,
            }

        with self.lock:
            try:
                st = self.run(read)
                self.last_error = None
                st["profile"] = self.cfg.get("active_profile")
                st["update"] = UPDATES.latest if UPDATES else None
                st["speaker_count"] = len(self.cfg.get("speakers", []))
                return st
            except Exception as err:  # noqa: BLE001
                self.last_error = str(err)
                log.debug("state failed: %s", err)
                return {"configured": True, "connected": False,
                        "host": self.client.host if self.client else None,
                        "error": str(err), "info": self.info}

    def _now_playing(self, c: KefClient) -> dict[str, Any] | None:
        try:
            ps = c.get_player_state()
        except Exception as err:  # noqa: BLE001 - not available on every source/firmware
            log.debug("player state unavailable: %s", err)
            return None
        t = ps.track
        pos = None
        if t is not None and t.duration_ms:
            try:
                pos = c.get_play_position()
            except Exception:  # noqa: BLE001
                pos = None
        return {
            "state": ps.state.value if hasattr(ps.state, "value") else str(ps.state),
            "title": t.title if t else None,
            "artist": t.artist if t else None,
            "album": t.album if t else None,
            "cover": t.cover_url if t else None,
            "duration": t.duration_ms if t else None,
            "position": pos,
            "live": bool(t.live) if t else False,
            "can": {"pause": ps.controls.pause, "next": ps.controls.next,
                    "previous": ps.controls.previous},
        }

    def playback(self, action: str) -> None:
        fns = {"playpause": lambda c: c.play_pause(), "next": lambda c: c.next_track(),
               "previous": lambda c: c.previous_track()}
        if action not in fns:
            raise ApiError(f"Unknown playback action {action}")
        self.run(fns[action])

    # -- controls --------------------------------------------------------------
    def power(self, on: bool, source: str | None = None) -> None:
        def do(c: KefClient) -> None:
            if on:
                c.power_on(source or self.cfg.get("last_source") or Source.USB)
            else:
                try:
                    src = c.get_source()
                    if src != Source.STANDBY:
                        self.cfg["last_source"] = src.value
                        save_config(self.cfg)
                except Exception:  # noqa: BLE001
                    pass
                c.power_off()
        self.run(do)

    def set_source(self, source: str) -> None:
        self.run(lambda c: c.set_source(Source(source)))
        with self.lock:
            self.cfg["last_source"] = source
            save_config(self.cfg)

    def set_volume(self, volume: int) -> None:
        self.run(lambda c: c.set_volume(max(0, min(100, int(volume)))))

    def step_volume(self, direction: int) -> int:
        return self.run(lambda c: c.volume_up() if direction > 0 else c.volume_down())

    def set_mute(self, muted: bool) -> None:
        self.run(lambda c: c.set_mute(bool(muted)))

    # -- EQ ----------------------------------------------------------------------
    def eq(self) -> dict[str, Any]:
        with self.lock:
            c = self._need()
            profile = c.get_eq_profile()
            ranges = c.get_eq_ranges()
            data = jsonable(profile)
            data.pop("extra", None)
            data.pop("extra_dsp", None)
            return {
                "profile": data,
                "ranges": {k: jsonable(v) for k, v in ranges.items()},
                "choices": {
                    "bass_extension": [m.value for m in BassExtension],
                    "subwoofer_preset": [m.value for m in SubwooferPreset],
                    "polarity": [m.value for m in Polarity],
                },
            }

    def update_eq(self, changes: dict[str, Any]) -> dict[str, Any]:
        typed: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in EDITABLE_EQ:
                raise ApiError(f"Unknown EQ field {key}")
            if key in ENUM_FIELDS:
                typed[key] = ENUM_FIELDS[key](str(value))
            elif key in BOOL_FIELDS:
                typed[key] = bool(value)
            elif key in INT_FIELDS:
                typed[key] = int(round(float(value)))
            else:
                typed[key] = float(value)
        with self.lock:
            try:
                self._need().update_eq_profile(**typed)
            except ValueError as err:
                raise ApiError(str(err)) from err
        return self.eq()

    def reset_eq(self) -> dict[str, Any]:
        with self.lock:
            self._need().reset_eq_profile()
        time.sleep(0.4)
        return self.eq()

    # -- settings -------------------------------------------------------------
    def _supported(self, d: dict[str, Any]) -> bool:
        feat = d.get("feature")
        if feat is None or self.capabilities is None:
            return True
        return self.capabilities.supports(feat)

    def settings(self) -> dict[str, Any]:
        with self.lock:
            c = self._need()
            if self.capabilities is None:
                self._load_info()
            out = []
            for d in SETTING_DEFS:
                if not self._supported(d):
                    continue
                try:
                    value = c.get_setting(d["setting"])
                except Exception as err:  # noqa: BLE001 - not on this model/firmware
                    log.debug("setting %s unavailable: %s", d["key"], err)
                    continue
                item = {k: v for k, v in d.items() if k not in ("setting", "feature")}
                if d["key"] == "wake_up_source" and self.capabilities is not None:
                    allowed = {"wakeup_default"} | {s.value for s in self.capabilities.sources}
                    item["choices"] = [c for c in d["choices"] if c[0] in allowed]
                py = d["setting"].py_type
                item["type"] = ("enum" if "choices" in d else "text" if d.get("text") else
                                "bool" if py is bool else "number")
                item["value"] = jsonable(value)
                out.append(item)
            default_vol = None
            try:
                default_vol = c.get_setting(Settings.DEFAULT_VOLUME_GLOBAL)
            except Exception:  # noqa: BLE001
                pass
            return {"settings": out, "default_volume": default_vol}

    def set_setting(self, key: str, value: Any) -> None:
        d = next((d for d in SETTING_DEFS if d["key"] == key), None)
        if d is None:
            raise ApiError(f"Unknown setting {key}")
        setting = d["setting"]
        py = setting.py_type
        if py is bool:
            value = bool(value)
        elif py is int:
            value = int(round(float(value)))
        elif py is float:
            value = float(value)
        elif py is str:
            value = str(value)
        else:
            value = py(str(value))
        with self.lock:
            try:
                self._need().set_setting(setting, value)
            except (ValueError, TypeError) as err:
                raise ApiError(str(err)) from err

    def set_default_volume(self, volume: int) -> None:
        with self.lock:
            self._need().set_default_volume(int(volume))

    # -- sound profiles ----------------------------------------------------------
    def _current_sound(self) -> dict[str, Any]:
        profile = self.run(lambda c: c.get_eq_profile())
        data = jsonable(profile)
        return {k: data[k] for k in PROFILE_KEYS if k in data}

    def profiles(self) -> dict[str, Any]:
        with self.lock:
            items = self.cfg.get("profiles") or []
            active = self.cfg.get("active_profile")
            modified = None
            prof = next((p for p in items if p["name"] == active), None)
            if prof is not None and self.client is not None:
                try:
                    cur = self._current_sound()
                    modified = any(not _same(cur.get(k), v) for k, v in prof["settings"].items())
                except Exception:  # noqa: BLE001
                    modified = None
            return {"profiles": items, "active": active if prof else None, "modified": modified,
                    "keys": PROFILE_KEYS}

    def save_profile(self, name: str, overwrite: bool = False) -> dict[str, Any]:
        name = " ".join(str(name).split())[:40]
        if not name:
            raise ApiError("Give the profile a name.")
        with self.lock:
            settings = self._current_sound()
            items = self.cfg.setdefault("profiles", [])
            existing = next((p for p in items if p["name"].lower() == name.lower()), None)
            if existing and not overwrite:
                raise ApiError(f'A profile called "{existing["name"]}" already exists.', 409)
            if existing:
                existing["settings"] = settings
                name = existing["name"]
            else:
                items.append({"name": name, "settings": settings})
            self.cfg["active_profile"] = name
            save_config(self.cfg)
        return self.profiles()

    def apply_profile(self, name: str) -> dict[str, Any]:
        with self.lock:
            prof = next((p for p in self.cfg.get("profiles") or [] if p["name"] == name), None)
            if prof is None:
                raise ApiError("That profile doesn't exist any more.", 404)
            changes = {k: v for k, v in prof["settings"].items() if k in PROFILE_KEYS}
            self.update_eq(changes)
            self.cfg["active_profile"] = name
            save_config(self.cfg)
        return self.profiles()

    def rename_profile(self, name: str, new: str) -> dict[str, Any]:
        new = " ".join(str(new).split())[:40]
        if not new:
            raise ApiError("Give the profile a name.")
        with self.lock:
            items = self.cfg.get("profiles") or []
            prof = next((p for p in items if p["name"] == name), None)
            if prof is None:
                raise ApiError("That profile doesn't exist any more.", 404)
            if any(p is not prof and p["name"].lower() == new.lower() for p in items):
                raise ApiError(f'A profile called "{new}" already exists.', 409)
            prof["name"] = new
            if self.cfg.get("active_profile") == name:
                self.cfg["active_profile"] = new
            save_config(self.cfg)
        return self.profiles()

    def delete_profile(self, name: str) -> dict[str, Any]:
        with self.lock:
            self.cfg["profiles"] = [p for p in self.cfg.get("profiles") or [] if p["name"] != name]
            if self.cfg.get("active_profile") == name:
                self.cfg.pop("active_profile", None)
            save_config(self.cfg)
        return self.profiles()

    def move_profile(self, name: str, delta: int) -> dict[str, Any]:
        with self.lock:
            items = self.cfg.get("profiles") or []
            i = next((i for i, p in enumerate(items) if p["name"] == name), None)
            if i is not None:
                j = max(0, min(len(items) - 1, i + delta))
                items.insert(j, items.pop(i))
                save_config(self.cfg)
        return self.profiles()

    # -- app settings ---------------------------------------------------------------
    def app_settings(self) -> dict[str, Any]:
        return {"check_updates": self.cfg.get("check_updates", True), "version": APP_VERSION,
                "store": IS_PACKAGED,
                "update": UPDATES.latest if UPDATES else None,
                "checked_at": UPDATES.checked_at if UPDATES else None, "repo": GITHUB_REPO}

    def set_app_setting(self, key: str, value: Any) -> dict[str, Any]:
        if key != "check_updates":
            raise ApiError(f"Unknown option {key}")
        with self.lock:
            self.cfg[key] = bool(value)
            save_config(self.cfg)
        return self.app_settings()

    # -- power sync settings ------------------------------------------------------
    def power_sync(self) -> dict[str, Any]:
        from powersync import LABELS, settings_from
        events = POWER.log if POWER is not None else []
        return {"settings": settings_from(self.cfg), "labels": LABELS,
                "supported": sys.platform == "win32",
                "log": [{"time": t, "event": e, "result": r} for t, e, r in events]}

    def set_power_sync(self, key: str, value: Any) -> dict[str, Any]:
        from powersync import DEFAULTS
        if key not in DEFAULTS:
            raise ApiError(f"Unknown option {key}")
        with self.lock:
            self.cfg.setdefault("power_sync", {})[key] = bool(value)
            save_config(self.cfg)
        return self.power_sync()

    def diagnostics(self) -> str:
        import platform
        try:
            from importlib.metadata import version as _v
            libver = _v("pykefcontrol")
        except Exception:  # noqa: BLE001
            libver = "?"
        st = self.state()
        info = st.get("info") or {}
        dev = info.get("device") or {}
        lines = [
            f"KEF Control {APP_VERSION}",
            f"Windows/OS: {platform.platform()}",
            f"Python {platform.python_version()} | pykefcontrol {libver}",
            f"Speaker: {dev.get('model_name') or info.get('model')} | firmware {info.get('firmware') or dev.get('firmware_version')}",
            f"Connection: {'connected' if st.get('connected') else 'NOT connected'} | "
            f"{'HTTPS' if info.get('secure') else 'HTTP'} | host {self.cfg.get('host')}",
            f"Input: {st.get('source')} | status {st.get('status')} | volume {st.get('volume')}",
            f"Saved speakers: {len(self.cfg.get('speakers', []))} | profiles: {len(self.cfg.get('profiles', []))}",
            f"Last error: {st.get('error') or self.last_error or 'none'}",
        ]
        if POWER is not None and POWER.log:
            lines.append("Power sync: " + "; ".join(f"{e} -> {r}" for _, e, r in POWER.log[-5:]))
        if RECENT_ERRORS:
            lines.append("Recent problems:")
            lines += [f"  {t} {m}" for t, m in list(RECENT_ERRORS)[-8:]]
        return "\n".join(lines)

    def reboot(self) -> None:
        with self.lock:
            self._need().reboot()


def norm_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    m = "".join(ch for ch in mac.lower() if ch in "0123456789abcdef")
    return m if len(m) == 12 and m != "000000000000" else None


def discover_raw(timeout: float = 3.0) -> list[Any]:
    from pykefcontrol.discovery import discover_blocking
    return discover_blocking(timeout)


def discover(timeout: float = 3.0) -> list[dict[str, Any]]:
    try:
        from pykefcontrol.discovery import discover_blocking
    except ImportError:
        raise ApiError("Discovery needs zeroconf: pip install \"pykefcontrol[discovery]\"") from None
    try:
        found = discover_blocking(timeout)
    except ImportError as err:
        raise ApiError(str(err)) from err
    return [{"host": s.host, "name": s.name, "model": s.marketing_name,
             "firmware": str(s.firmware) if s.firmware else None} for s in found]


# --------------------------------------------------------------------------- #
# HTTP server
# --------------------------------------------------------------------------- #


class Lifetime:
    """Shuts the app down once the UI window has been closed."""

    def __init__(self) -> None:
        self.last_beat = time.monotonic()
        self.bye_at: float | None = None
        self.seen_ui = False
        self.enabled = True

    def beat(self) -> None:
        self.last_beat = time.monotonic()
        self.bye_at = None
        self.seen_ui = True

    def bye(self) -> None:
        self.bye_at = time.monotonic()

    def should_exit(self) -> bool:
        if not self.enabled or not self.seen_ui:
            return False
        now = time.monotonic()
        if self.bye_at is not None and now - self.bye_at > 4:
            return True
        return now - self.last_beat > 120


MANAGER: SpeakerManager
LIFETIME = Lifetime()
ON_QUIT = None  # set in main(); called by POST /api/quit
POWER = None  # powersync.PowerSync, set in main()
UPDATES = None  # UpdateChecker, set in main()


class Handler(BaseHTTPRequestHandler):
    server_version = "KEFControl/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet
        log.debug("%s - " + fmt, self.address_string(), *args)

    # Protect against DNS rebinding / other sites poking the local API.
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin:
            o = urlparse(origin).hostname
            if o not in ("127.0.0.1", "localhost"):
                return False
        return True

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            data = json.loads(self.rfile.read(n))
        except ValueError:
            raise ApiError("Invalid JSON") from None
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            if path == "/icon.png":
                return self._send(200, (HERE / "icon.png").read_bytes(), "image/png")
            if path == "/favicon.ico":
                return self._send(200, (HERE / "kef_control.ico").read_bytes(), "image/x-icon")
            if path == "/api/state":
                LIFETIME.beat()
                return self._json(MANAGER.state())
            if path == "/api/eq":
                return self._json(MANAGER.eq())
            if path == "/api/settings":
                return self._json(MANAGER.settings())
            if path == "/api/discover":
                return self._json({"speakers": discover()})
            if path == "/api/profiles":
                return self._json(MANAGER.profiles())
            if path == "/api/speakers":
                return self._json(MANAGER.speakers())
            if path == "/api/app":
                return self._json(MANAGER.app_settings())
            if path == "/api/diagnostics":
                return self._send(200, MANAGER.diagnostics().encode("utf-8"), "text/plain; charset=utf-8")
            if path == "/api/powersync":
                return self._json(MANAGER.power_sync())
            if path == "/api/ping":
                return self._json({"app": APP_NAME, "version": APP_VERSION})
            self._send(404, b"not found", "text/plain")
        except ApiError as err:
            self._json({"error": str(err)}, err.status)
        except Exception as err:  # noqa: BLE001
            log.debug(traceback.format_exc())
            self._json({"error": str(err) or err.__class__.__name__}, 502)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        path = urlparse(self.path).path
        try:
            body = self._body()
            m = MANAGER
            if path == "/api/connect":
                return self._json(m.connect(str(body.get("host", ""))))
            if path == "/api/forget":
                m.forget()
                return self._json({"ok": True})
            if path == "/api/power":
                m.power(bool(body.get("on")))
            elif path == "/api/source":
                m.set_source(str(body["source"]))
            elif path == "/api/volume":
                if "step" in body:
                    return self._json({"volume": m.step_volume(int(body["step"]))})
                m.set_volume(int(body["volume"]))
            elif path == "/api/mute":
                m.set_mute(bool(body.get("muted")))
            elif path == "/api/eq":
                return self._json(m.update_eq(body))
            elif path == "/api/eq/reset":
                return self._json(m.reset_eq())
            elif path == "/api/settings":
                m.set_setting(str(body["key"]), body.get("value"))
            elif path == "/api/default_volume":
                m.set_default_volume(int(body["volume"]))
            elif path == "/api/profiles/save":
                return self._json(m.save_profile(body.get("name", ""), bool(body.get("overwrite"))))
            elif path == "/api/profiles/apply":
                return self._json(m.apply_profile(str(body["name"])))
            elif path == "/api/profiles/rename":
                return self._json(m.rename_profile(str(body["name"]), str(body.get("new", ""))))
            elif path == "/api/profiles/delete":
                return self._json(m.delete_profile(str(body["name"])))
            elif path == "/api/profiles/move":
                return self._json(m.move_profile(str(body["name"]), int(body.get("delta", 0))))
            elif path == "/api/playback":
                m.playback(str(body.get("action", "")))
            elif path == "/api/speakers/switch":
                return self._json(m.switch_speaker(str(body["id"])))
            elif path == "/api/speakers/remove":
                return self._json(m.remove_speaker(str(body["id"])))
            elif path == "/api/app":
                return self._json(m.set_app_setting(str(body["key"]), body.get("value")))
            elif path == "/api/update/check":
                if UPDATES is not None:
                    UPDATES.check()
                return self._json(m.app_settings())
            elif path == "/api/open":
                url = str(body.get("url", ""))
                if url.startswith(f"https://github.com/{GITHUB_REPO}"):
                    webbrowser.open(url)
            elif path == "/api/powersync":
                return self._json(m.set_power_sync(str(body["key"]), body.get("value")))
            elif path == "/api/reboot":
                m.reboot()
            elif path == "/api/bye":
                LIFETIME.bye()
            elif path == "/api/quit":
                if ON_QUIT is not None:
                    threading.Timer(0.2, ON_QUIT).start()
            else:
                return self._send(404, b"not found", "text/plain")
            self._json({"ok": True})
        except ApiError as err:
            self._json({"error": str(err)}, err.status)
        except (KeyError, ValueError, TypeError) as err:
            self._json({"error": f"Bad request: {err}"}, 400)
        except Exception as err:  # noqa: BLE001
            log.debug(traceback.format_exc())
            self._json({"error": str(err) or err.__class__.__name__}, 502)


# --------------------------------------------------------------------------- #
# Window
# --------------------------------------------------------------------------- #


def find_browser() -> str | None:
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                           Path(base) / "Google/Chrome/Application/chrome.exe"]
    for c in candidates:
        if c.exists():
            return str(c)
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None


WINDOW_TITLE = "KEF Control"  # must match <title> in ui.html
_last_launch = 0.0


def focus_existing_window() -> bool:
    """Bring an already-open KEF Control window to the front. True if one was found."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # noqa: N806

    def cb(hwnd, _lparam):  # noqa: ANN001, ANN202
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0 or n > 200:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value != WINDOW_TITLE:
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value.startswith("Chrome_WidgetWin"):  # Edge / Chrome app window
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    if not found:
        return False
    for extra in found[1:]:  # tidy up duplicates from older versions
        user32.PostMessageW(extra, 0x0010, 0, 0)  # WM_CLOSE
    hwnd = found[0]
    SW_RESTORE, SW_SHOW = 9, 5  # noqa: N806
    user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
    # Windows only lets the foreground app hand focus to another window; a synthetic
    # Alt key press makes this process eligible (standard workaround).
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    return True


def open_window(url: str) -> subprocess.Popen | None:
    """Show the KEF Control window: focus the existing one, or open it if there is none."""
    global _last_launch
    try:
        if focus_existing_window():
            return None
    except Exception:  # noqa: BLE001
        log.debug("focus_existing_window failed", exc_info=True)
    # A window was just launched and is still starting up: don't open a second one.
    if time.monotonic() - _last_launch < 6:
        return None
    _last_launch = time.monotonic()
    browser = find_browser()
    if browser:
        profile = config_dir() / "window-profile"
        args = [browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=460,820",
                "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
        try:
            flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
            return subprocess.Popen(args, creationflags=flags)
        except OSError as err:
            log.warning("Could not start %s: %s", browser, err)
    webbrowser.open(url)
    return None


def already_running() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5) as s:
            s.sendall(b"GET /api/ping HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while len(data) < 65536:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            return b"KEF Control" in data
    except OSError:
        return False


def request_quit(timeout: float = 8.0) -> None:
    """Ask a running instance to exit and wait until it has (used by the installer/uninstaller)."""
    if not already_running():
        return
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2) as s:
            s.sendall(b"POST /api/quit HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\n\r\n")
            while s.recv(4096):
                pass
    except OSError:
        return
    end = time.monotonic() + timeout
    while time.monotonic() < end and already_running():
        time.sleep(0.25)
    time.sleep(1.0)  # let the process finish exiting so its files are unlocked


def main() -> None:
    global MANAGER, ON_QUIT, POWER, UPDATES
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--background", action="store_true",
                    help="start in the system tray without opening the window (used at Windows startup)")
    ap.add_argument("--no-tray", action="store_true",
                    help="no tray icon: quit when the window is closed")
    ap.add_argument("--no-window", action="store_true", help="server only; open http://127.0.0.1:47801 yourself")
    ap.add_argument("--autostart", choices=["on", "off"], help="turn 'Start with Windows' on or off, then exit")
    ap.add_argument("--quit", action="store_true", help="ask a running KEF Control to exit, then exit")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    globals()["PORT"] = args.port

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not args.debug:
        logging.getLogger("pykefcontrol").setLevel(logging.WARNING)
    url = f"http://127.0.0.1:{PORT}/"

    if args.quit:
        request_quit()
        return

    if args.autostart:
        from tray import set_autostart
        set_autostart(args.autostart == "on", Path(__file__).resolve())
        return

    if already_running():
        if not args.background:
            open_window(url)
        return

    MANAGER = SpeakerManager()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as err:
        msg = (f"KEF Control couldn't start because port {PORT} is in use by another program.\n\n{err}")
        log.error(msg)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
        sys.exit(1)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Serving on %s", url)

    if args.no_window:
        LIFETIME.enabled = False
        stop = threading.Event()
        ON_QUIT = stop.set
        print(f"{APP_NAME} running at {url}  (Ctrl+C to quit)")
        try:
            while not stop.wait(3600):
                pass
        except KeyboardInterrupt:
            pass
        return

    UPDATES = UpdateChecker(lambda: bool(MANAGER.cfg.get("check_updates", True)) and not IS_PACKAGED)
    UPDATES.start()
    from powersync import PowerSync, WindowsListener, settings_from
    POWER = PowerSync(MANAGER, lambda: settings_from(MANAGER.cfg))
    WindowsListener(POWER.event).start()
    if args.background:
        # Started by Windows at sign-in: treat as "PC started".
        threading.Thread(target=POWER.event, args=("startup",), daemon=True).start()

    tray = None
    if not args.no_tray:
        try:
            from tray import Tray
            tray = Tray(MANAGER, lambda: open_window(url), server.shutdown,
                        HERE / "kef_control.ico", Path(__file__).resolve())
        except Exception:  # noqa: BLE001 - pystray missing or no tray available
            log.warning("Tray icon unavailable, running window-only", exc_info=args.debug)
            tray = None

    if tray is not None:
        ON_QUIT = tray.quit
        # Tray mode: closing the window does not quit; use the tray menu's Quit.
        LIFETIME.enabled = False
        if not args.background:
            open_window(url)
        tray.run()  # blocks until Quit
        server.shutdown()
        os._exit(0)

    stop = threading.Event()
    ON_QUIT = stop.set
    open_window(url)
    try:
        # The UI sends a heartbeat while open and a "bye" beacon when closed.
        while not LIFETIME.should_exit() and not stop.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    server.shutdown()


if __name__ == "__main__":
    main()
