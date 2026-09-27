"""Valida que nosso XOR+Base64 bate com o da SPA para um Date fixo."""
import base64
import json
from datetime import datetime, timezone


KEY = "-5Hsrpt5gb93N5L9ePT2bBC9MI9ThLctvltkuoOqh2Q"


def spa_style_hash(iso: str) -> str:
    # JSON.stringify(new Date) => "\"2026-...\"" 
    plaintext = json.dumps(iso)
    out = []
    for i, ch in enumerate(plaintext):
        out.append(ord(ch) ^ ord(KEY[i % len(KEY)]))
    return base64.b64encode(bytes(out)).decode("ascii")


def old_style_hash(iso: str) -> str:
    plaintext = f'"{iso}"'
    out = []
    for i, ch in enumerate(plaintext):
        out.append(ord(ch) ^ ord(KEY[i % len(KEY)]))
    return base64.b64encode(bytes(out)).decode("ascii")


iso = "2026-09-08T00:04:09.748Z"
print("iso", iso)
print("json.dumps", json.dumps(iso))
print("spa_style", spa_style_hash(iso))
print("old_style", old_style_hash(iso))
print("same?", spa_style_hash(iso) == old_style_hash(iso))
