"""Fake KEF LSX II LT HTTP API (port 80) for testing KEF Control."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

def t(kind, v):
    return {"type": kind, kind: v}

STORE = {
    "settings:/kef/host/modelName": t("string_", "SP4077"),
    "settings:/version": t("string_", "2.3.10.0xabc"),
    "settings:/releasetext": t("string_", "LSXIILT_V2310"),
    "settings:/deviceName": t("string_", "Desk Speakers"),
    "settings:/kef/host/serialNumber": t("string_", "LT123456"),
    "settings:/system/primaryMacAddress": t("string_", "84:17:15:00:11:22"),
    "settings:/kef/play/physicalSource": t("kefPhysicalSource", "usb"),
    "settings:/kef/host/speakerStatus": t("kefSpeakerStatus", "powerOn"),
    "player:volume": t("i32_", 35),
    "settings:/mediaPlayer/mute": t("bool_", False),
    "settings:/kef/host/standbyMode": t("kefStandbyMode", "standby_20mins"),
    "settings:/kef/host/wakeUpSource": t("kefWakeUpSource", "wakeup_default"),
    "settings:/kef/host/autoSwitchToHDMI": t("bool_", True),
    "settings:/kef/host/startupTone": t("bool_", False),
    "settings:/kef/host/volumeLimit": t("bool_", False),
    "settings:/kef/host/maximumVolume": t("i32_", 100),
    "settings:/kef/host/volumeStep": t("i16_", 2),
    "settings:/kef/host/standbyDefaultVol": t("bool_", False),
    "settings:/kef/host/defaultVolumeGlobal": t("i32_", 30),
    "settings:/kef/host/disableFrontLED": t("bool_", False),
    "settings:/kef/host/disableFrontStandbyLED": t("bool_", False),
    "settings:/kef/host/usbCharging": t("bool_", True),
    "settings:/kef/host/masterChannelMode": t("kefMasterChannelMode", "right"),
    "settings:/kef/host/subwooferForceOn": t("bool_", False),
    "kef:eqProfile/v2": t("kefEqProfileV2", {
        "profileName": "", "profileId": "", "isExpertMode": False, "balance": 0,
        "deskMode": True, "deskModeSetting": -3.0, "wallMode": False, "wallModeSetting": 0.0,
        "phaseCorrection": True, "trebleAmount": 0.0, "highPassMode": False, "highPassModeFreq": 95,
        "subwooferPolarity": "normal", "subOutLPFreq": 80, "bassExtension": "standard",
        "subwooferGain": 0, "subEnableStereo": False, "audioPolarity": "normal", "isKW1": False,
        "subwooferCount": 0, "subwooferPreset": "custom", "subwooferOut": False}),
}
LOG = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, data):
        b = json.dumps(data).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/api/getData":
            p = q["path"][0]
            if p in STORE: return self._j(200, [STORE[p]])
            return self._j(500, {"error": {"name": "invalidPath", "message": f"Node at path '{p}' does not exist"}})
        if u.path == "/api/getRows":
            return self._j(500, {"error": {"message": "no rows"}})
        self._j(404, {})
    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LOG.append(b); print("SET", json.dumps(b), flush=True)
        p = b["path"]
        if b.get("role") == "activate":
            return self._j(200, {})
        if p in STORE or p.startswith("settings:"):
            STORE[p] = b["value"]
            if p == "settings:/kef/play/physicalSource":
                STORE["settings:/kef/host/speakerStatus"] = t("kefSpeakerStatus", "standby" if b["value"]["kefPhysicalSource"] == "standby" else "powerOn")
            return self._j(200, {})
        if p == "player:volume":
            STORE[p] = b["value"]; return self._j(200, {})
        self._j(500, {"error": {"message": "bad path"}})

ThreadingHTTPServer(("127.0.0.1", 80), H).serve_forever()
