"""
Instala a extensão unpacked de Inclusão Forms no Chrome e no Edge (perfil local).
Fecha os navegadores, habilita modo desenvolvedor e registra o path da extensão.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EXT_DIR = Path(r"C:\site-record\chrome_extension_inclusao_forms").resolve()
MANIFEST_PATH = EXT_DIR / "manifest.json"
KEY_PEM_PATH = EXT_DIR / ".dev_private_key.pem"

CHROME_USER_DATA = Path(os.environ["LOCALAPPDATA"]) / "Google" / "Chrome" / "User Data"
EDGE_USER_DATA = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data"

CHROME_EXE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
EDGE_EXE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def chrome_id_from_der(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(ch, 16)) for ch in digest)


def ensure_manifest_key() -> tuple[str, str]:
    """Garante 'key' no manifest e retorna (extension_id, key_b64)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    key_b64 = (manifest.get("key") or "").strip()

    if key_b64:
        der = base64.b64decode(key_b64)
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        KEY_PEM_PATH.write_bytes(pem)
        der = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        key_b64 = base64.b64encode(der).decode("ascii")
        manifest["key"] = key_b64
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return chrome_id_from_der(der), key_b64


def kill_browsers() -> None:
    for name in ("chrome.exe", "msedge.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", name, "/T"],
            capture_output=True,
            text=True,
            check=False,
        )
    time.sleep(2)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def list_profiles(user_data: Path) -> list[Path]:
    if not user_data.is_dir():
        return []
    profiles: list[Path] = []
    for child in user_data.iterdir():
        if not child.is_dir():
            continue
        if child.name == "Default" or child.name.startswith("Profile "):
            if (child / "Preferences").exists():
                profiles.append(child)
    return profiles


def install_into_profile(profile_dir: Path, ext_id: str, manifest: dict) -> bool:
    prefs_path = profile_dir / "Preferences"
    if not prefs_path.exists():
        return False
    prefs = load_json(prefs_path)
    extensions = prefs.setdefault("extensions", {})
    ui = extensions.setdefault("ui", {})
    ui["developer_mode"] = True
    settings = extensions.setdefault("settings", {})

    path_str = str(EXT_DIR)
    entry = {
        "active_permissions": {
            "api": list(manifest.get("permissions") or []),
            "explicit_host": list(manifest.get("host_permissions") or []),
            "manifest_permissions": [],
            "scriptable_host": [],
        },
        "commands": {},
        "content_settings": [],
        "creation_flags": 1,
        "from_webstore": False,
        "granted_permissions": {
            "api": list(manifest.get("permissions") or []),
            "explicit_host": list(manifest.get("host_permissions") or []),
            "manifest_permissions": [],
            "scriptable_host": [],
        },
        "install_time": "13370000000000000",
        "location": 4,
        "newAllowFileAccess": True,
        "path": path_str,
        "manifest": {k: v for k, v in manifest.items() if k != "key"},
        "state": 1,
        "was_installed_by_default": False,
        "was_installed_by_oem": False,
        "withholding_permissions": False,
    }
    # Mantém key no manifest embutido se existir
    if "key" in manifest:
        entry["manifest"]["key"] = manifest["key"]

    settings[ext_id] = entry
    save_json(prefs_path, prefs)
    return True


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"ERRO: manifest não encontrado em {MANIFEST_PATH}")
        return 1

    ext_id, _key = ensure_manifest_key()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(f"Extensão ID: {ext_id}")
    print(f"Path: {EXT_DIR}")

    print("Fechando Chrome e Edge...")
    kill_browsers()

    installed: list[str] = []
    for label, user_data in (("Chrome", CHROME_USER_DATA), ("Edge", EDGE_USER_DATA)):
        profiles = list_profiles(user_data)
        if not profiles:
            print(f"{label}: nenhum perfil encontrado em {user_data}")
            continue
        for profile in profiles:
            ok = install_into_profile(profile, ext_id, manifest)
            status = "OK" if ok else "FALHOU"
            print(f"{label} / {profile.name}: {status}")
            if ok:
                installed.append(f"{label}:{profile.name}")

    if not installed:
        print("Nenhuma instalação realizada.")
        return 2

    # Reabre navegadores na página de extensões + Auditoria
    if CHROME_EXE.exists():
        subprocess.Popen(
            [
                str(CHROME_EXE),
                "chrome://extensions",
                "https://www.recordpap.com.br/auditoria/",
            ]
        )
        print("Chrome reaberto.")
    if EDGE_EXE.exists():
        subprocess.Popen(
            [
                str(EDGE_EXE),
                "edge://extensions",
                "https://www.recordpap.com.br/auditoria/",
            ]
        )
        print("Edge reaberto.")

    print("Concluído. Confira se a extensão aparece ativa e recarregue a Auditoria.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
