import io
import zipfile

from django.test import SimpleTestCase, override_settings

from crm_app.sonax_voice_service import (
    SonaxVoiceService,
    _parse_sonax_status_chamada,
    unpack_recording_zip,
)
from crm_app.auditoria_ligacoes_api import (
    _finalizada_por_status,
    _merge_webhook_payload,
    _resolved_voice_provider,
    _webhook_call_id,
)


@override_settings(
    SONAX_CLICK2CALL_TOKEN="t",
    SONAX_ID_CLIENTE="1",
    SONAX_INTEGRATION_TOKEN="t",
)
class SonaxVoiceServiceParseTest(SimpleTestCase):
    def test_extract_protocol_from_html_message(self):
        svc = SonaxVoiceService()
        self.assertEqual(
            svc._extract_protocol_from_text("PROTOCOLO 998877 da Ligacao Realizada para 31999999999"),
            "998877",
        )

    def test_extract_protocol_from_click2call_started_message(self):
        svc = SonaxVoiceService()
        self.assertEqual(
            svc._extract_protocol_from_text("Ligação iniciada. ID: 20 | Provedor: sem_id_1774555202.672607"),
            "20",
        )

    def test_extract_protocol_from_quoted_digits(self):
        svc = SonaxVoiceService()
        self.assertEqual(
            svc._extract_protocol_from_text('""19101782792""'),
            "19101782792",
        )

    def test_parse_status_chamada_pipe_separated(self):
        parsed = _parse_sonax_status_chamada(
            "desligada|123|456|2026-03-26 18:00:00|2026-03-26 18:00:12|S|12|101|5531988804000"
        )
        self.assertEqual(parsed["status_chamada"], "desligada")
        self.assertEqual(parsed["status_atendimento"], "S")
        self.assertEqual(parsed["duracao_segundos"], 12)
        self.assertEqual(parsed["numero_ramal"], "101")
        self.assertEqual(parsed["numero_discado"], "5531988804000")

    def test_parse_json_response_body(self):
        svc = SonaxVoiceService()
        import requests

        r = requests.Response()
        r.status_code = 200
        r._content = b'{"id_chamada": "42", "ok": true}'
        r.headers["content-type"] = "application/json"
        parsed = svc._parse_click2call_response(r)
        self.assertEqual(parsed.get("id_chamada"), "42")

    def test_unpack_recording_zip_prefere_mp3(self):
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, mode="w") as zf:
            zf.writestr("a.wav", b"WAV")
            zf.writestr("b.mp3", b"MP3")
        content, ext = unpack_recording_zip(mem.getvalue(), prefer_mp3=True)
        self.assertEqual(ext, ".mp3")
        self.assertEqual(content, b"MP3")


class AuditoriaWebhookHelpersTest(SimpleTestCase):
    def test_merge_query_and_body(self):
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        django_req = factory.get("/hook/", {"id_chamada": "7", "duracao": "15"})
        merged = _merge_webhook_payload(Request(django_req))
        self.assertEqual(merged.get("id_chamada"), "7")
        self.assertEqual(merged.get("duracao"), "15")

    def test_call_id_keys(self):
        self.assertEqual(_webhook_call_id({"id_chamada": "99"}), "99")
        self.assertEqual(_webhook_call_id({"ID_CHAMADA": "100"}), "100")

    def test_sonax_finalizada_status(self):
        self.assertTrue(_finalizada_por_status("SONAX", "desligada"))
        self.assertFalse(_finalizada_por_status("SONAX", "discando"))


class ResolvedVoiceProviderTest(SimpleTestCase):
    @override_settings(AUDITORIA_VOICE_PROVIDER="sonax", SONAX_CLICK2CALL_TOKEN="")
    def test_explicit_sonax_even_without_token(self):
        self.assertEqual(_resolved_voice_provider(), "sonax")

    @override_settings(
        AUDITORIA_VOICE_PROVIDER="auto",
        SONAX_CLICK2CALL_TOKEN="token",
        ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER="5531999999999",
    )
    def test_auto_prefers_sonax_when_configured(self):
        self.assertEqual(_resolved_voice_provider(), "sonax")

    @override_settings(
        AUDITORIA_VOICE_PROVIDER="auto",
        SONAX_CLICK2CALL_TOKEN="",
        SONAX_INTEGRATION_TOKEN="",
        ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER="5531999999999",
    )
    def test_auto_uses_zenvia_only_when_sonax_absent(self):
        self.assertEqual(_resolved_voice_provider(), "zenvia")

    @override_settings(
        AUDITORIA_VOICE_PROVIDER="auto",
        SONAX_CLICK2CALL_TOKEN="",
        SONAX_INTEGRATION_TOKEN="",
        ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER="",
    )
    def test_auto_defaults_to_sonax(self):
        self.assertEqual(_resolved_voice_provider(), "sonax")
