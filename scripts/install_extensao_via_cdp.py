"""
Instala a extensão unpacked no Chrome/Edge via CDP (Chrome 137+).
Requer navegador iniciado com:
  --remote-debugging-port=PORT
  --enable-unsafe-extension-debugging
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

EXT_DIR = str(Path(r"C:\site-record\chrome_extension_inclusao_forms").resolve())


def cdp_http(port: int, path: str) -> dict | list:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_unpacked(port: int) -> None:
    import websocket  # type: ignore

    ver = cdp_http(port, "/json/version")
    ws_url = ver["webSocketDebuggerUrl"]
    ws = websocket.create_connection(ws_url, timeout=10)
    try:
        msg_id = 1
        payload = {
            "id": msg_id,
            "method": "Extensions.loadUnpacked",
            "params": {"path": EXT_DIR},
        }
        ws.send(json.dumps(payload))
        deadline = time.time() + 15
        while time.time() < deadline:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(data["error"])
                print("OK loadUnpacked:", data.get("result"))
                return
        raise TimeoutError("Sem resposta do CDP Extensions.loadUnpacked")
    finally:
        ws.close()


def launch(browser: str, exe: Path, port: int) -> None:
    name = "chrome.exe" if browser == "chrome" else "msedge.exe"
    subprocess.run(["taskkill", "/F", "/IM", name, "/T"], capture_output=True)
    time.sleep(2)
    args = [
        str(exe),
        f"--remote-debugging-port={port}",
        "--enable-unsafe-extension-debugging",
        "https://www.recordpap.com.br/auditoria/",
        "chrome://extensions/" if browser == "chrome" else "edge://extensions/",
    ]
    subprocess.Popen(args)
    # espera o debugger
    for _ in range(30):
        try:
            cdp_http(port, "/json/version")
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"CDP não subiu na porta {port}")


def main() -> int:
    try:
        import websocket  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "websocket-client", "-q"])

    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

    if chrome.exists():
        print("=== Chrome ===")
        launch("chrome", chrome, 9222)
        time.sleep(1)
        load_unpacked(9222)

    if edge.exists():
        print("=== Edge ===")
        launch("edge", edge, 9223)
        time.sleep(1)
        try:
            load_unpacked(9223)
        except Exception as e:
            print("Edge loadUnpacked falhou (pode precisar carregar manualmente):", e)

    print("Concluído. Dê F5 na Auditoria.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
