"""Serviço de resolução de reCAPTCHA v2.

Por padrão usa CapSolver (melhor latência e taxa de sucesso que 2Captcha em v2 checkbox).
Suporta também 2captcha e API customizada (RECAPTCHA_SOLVER_API_URL).
"""
from __future__ import annotations

import os
import time
from typing import Literal, Optional

import requests

CaptchaProvider = Literal["capsolver", "2captcha", "custom"]


class RecaptchaSolver:
    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        timeout: int = 120,
        poll_interval: int = 3,
        custom_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("CAPTCHA_API_KEY")
        self.provider = (provider or os.getenv("CAPTCHA_PROVIDER", "capsolver")).lower()
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.custom_url = custom_url or os.getenv("RECAPTCHA_SOLVER_API_URL", "").strip()

    def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        if self.provider == "custom":
            if not self.custom_url:
                raise RuntimeError("RECAPTCHA_SOLVER_API_URL ausente para provedor 'custom'")
            return self._solve_custom(site_key, page_url)
        if not self.api_key:
            raise RuntimeError("CAPTCHA_API_KEY ausente")
        if self.provider == "capsolver":
            return self._solve_capsolver(site_key, page_url)
        if self.provider == "2captcha":
            return self._solve_2captcha(site_key, page_url)
        raise ValueError(f"Provedor de captcha não suportado: {self.provider}")

    def _solve_custom(self, site_key: str, page_url: str) -> Optional[str]:
        """Chama API customizada: POST com JSON { siteKey, pageUrl } e espera { token } ou { gRecaptchaResponse }."""
        payload = {"siteKey": site_key, "pageUrl": page_url}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            payload["apiKey"] = self.api_key
        try:
            r = requests.post(self.custom_url, json=payload, headers=headers, timeout=int(self.timeout))
            r.raise_for_status()
            data = r.json()
            return data.get("token") or data.get("gRecaptchaResponse") or data.get("solution", {}).get("gRecaptchaResponse")
        except Exception:
            return None

    # CapSolver
    def _solve_capsolver(self, site_key: str, page_url: str) -> Optional[str]:
        create_payload = {
            "clientKey": self.api_key,
            "task": {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": page_url,
                "websiteKey": site_key,
            },
        }
        task_id = self._post_json("https://api.capsolver.com/createTask", create_payload).get("taskId")
        if not task_id:
            return None
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            time.sleep(self.poll_interval)
            res = self._post_json(
                "https://api.capsolver.com/getTaskResult",
                {"clientKey": self.api_key, "taskId": task_id},
            )
            if res.get("status") == "ready":
                return res.get("solution", {}).get("gRecaptchaResponse")
        return None

    # 2Captcha (mantido para fallback/testes A/B)
    def _solve_2captcha(self, site_key: str, page_url: str) -> Optional[str]:
        params = {
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }
        create = requests.get("https://2captcha.com/in.php", params=params, timeout=15)
        data = create.json()
        if data.get("status") != 1:
            return None
        request_id = data.get("request")
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            time.sleep(self.poll_interval)
            poll = requests.get(
                "https://2captcha.com/res.php",
                params={"key": self.api_key, "action": "get", "id": request_id, "json": 1},
                timeout=15,
            ).json()
            if poll.get("status") == 1:
                return poll.get("request")
            if poll.get("request") not in {"CAPCHA_NOT_READY", None}:
                break
        return None

    @staticmethod
    def _post_json(url: str, payload: dict) -> dict:
        try:
            resp = requests.post(url, json=payload, timeout=20)
            return resp.json()
        except Exception:
            return {}
