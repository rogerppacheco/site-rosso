"""Injeta a extensão unpacked no perfil Default do Chrome (navegador fechado)."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

EXT_ID = "cgmpkggpemhfojadajkcofmjmbhbihla"
EXT_DIR = Path(r"C:\site-record\chrome_extension_inclusao_forms").resolve()
PREFS = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data" / "Default" / "Preferences"
EDGE_PREFS = [
    Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data" / "Default" / "Preferences",
    Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data" / "Profile 1" / "Preferences",
]


def kill(name: str) -> None:
    subprocess.run(["taskkill", "/F", "/IM", name, "/T"], capture_output=True)
    time.sleep(2)


def inject(prefs_path: Path) -> None:
    if not prefs_path.exists():
        print("skip missing", prefs_path)
        return
    manifest = json.loads((EXT_DIR / "manifest.json").read_text(encoding="utf-8"))
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    extensions = prefs.setdefault("extensions", {})
    extensions.setdefault("ui", {})["developer_mode"] = True
    settings = extensions.setdefault("settings", {})

    path_str = str(EXT_DIR)
    settings[EXT_ID] = {
        "account_extension_type": 0,
        "active_permissions": {
            "api": list(manifest.get("permissions") or []),
            "explicit_host": list(manifest.get("host_permissions") or []),
            "manifest_permissions": [],
            "scriptable_host": [
                "https://recordpap.com.br/*",
                "https://www.recordpap.com.br/*",
                "http://localhost:8000/*",
                "http://127.0.0.1:8000/*",
                "https://docs.google.com/forms/*",
            ],
        },
        "commands": {},
        "content_settings": [],
        "creation_flags": 1,
        "disable_reasons": [],
        "from_webstore": False,
        "granted_permissions": {
            "api": list(manifest.get("permissions") or []),
            "explicit_host": list(manifest.get("host_permissions") or []),
            "manifest_permissions": [],
            "scriptable_host": [
                "https://recordpap.com.br/*",
                "https://www.recordpap.com.br/*",
                "http://localhost:8000/*",
                "http://127.0.0.1:8000/*",
                "https://docs.google.com/forms/*",
            ],
        },
        "install_time": "13351234567890123",
        "location": 4,
        "newAllowFileAccess": True,
        "path": path_str,
        "manifest": manifest,
        "state": 1,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
        "withholding_permissions": False,
    }
    prefs_path.write_text(json.dumps(prefs, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("injected", prefs_path)


def verify(prefs_path: Path) -> bool:
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    e = ((prefs.get("extensions") or {}).get("settings") or {}).get(EXT_ID)
    ok = bool(e) and e.get("state") == 1
    print("verify", prefs_path.parent.name, ok, (e or {}).get("path"))
    return ok


def main() -> None:
    kill("chrome.exe")
    kill("msedge.exe")
    time.sleep(2)
    inject(PREFS)
    for p in EDGE_PREFS:
        inject(p)

    # Abre só a página de extensões para o usuário confirmar
    subprocess.Popen(
        [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "chrome://extensions/?id=" + EXT_ID,
        ]
    )
    subprocess.Popen(
        [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "edge://extensions/",
        ]
    )
    time.sleep(6)
    print("--- after start ---")
    verify(PREFS)
    for p in EDGE_PREFS:
        if p.exists():
            verify(p)


if __name__ == "__main__":
    main()
