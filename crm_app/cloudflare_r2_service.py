"""
Upload de arquivos para Cloudflare R2 (API S3-compatível).

Estrutura de chaves: {R2_FOLDER_ROOT}/{pasta_funcional}/{subpastas}/{arquivo}
Ex.: CDOI_Record_Vertical/Record_Apoia/material.pdf
"""
from __future__ import annotations

import logging
import mimetypes
import re
import urllib.parse
from io import BytesIO
from typing import BinaryIO, Union

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)

FileLike = Union[BinaryIO, BytesIO]


class CloudflareR2StorageError(Exception):
    """Erro ao interagir com o bucket R2."""


class CloudflareR2Storage:
    """Cliente de upload para Cloudflare R2 com URL pública estável."""

    def __init__(self) -> None:
        self.account_id = settings.CLOUDFLARE_R2_ACCOUNT_ID
        self.access_key_id = settings.CLOUDFLARE_R2_ACCESS_KEY_ID
        self.secret_access_key = settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY
        self.bucket_name = settings.CLOUDFLARE_R2_BUCKET_NAME
        self.public_base_url = (settings.CLOUDFLARE_R2_PUBLIC_URL or "").rstrip("/")
        self.folder_root = settings.R2_FOLDER_ROOT.strip("/")

        if not all([self.account_id, self.access_key_id, self.secret_access_key, self.bucket_name]):
            raise CloudflareR2StorageError(
                "Credenciais R2 incompletas. Configure CLOUDFLARE_R2_ACCOUNT_ID, "
                "CLOUDFLARE_R2_ACCESS_KEY_ID, CLOUDFLARE_R2_SECRET_ACCESS_KEY e "
                "CLOUDFLARE_R2_BUCKET_NAME."
            )

        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    def _build_object_key(self, folder_name: str, filename: str) -> str:
        """Monta a chave do objeto com prefixo raiz e pastas por função."""
        safe_folder = "/".join(
            part.strip("/")
            for part in (folder_name or "").split("/")
            if part and part.strip("/")
        )
        safe_filename = (filename or "arquivo").replace("\\", "/").split("/")[-1]
        parts = [self.folder_root]
        if safe_folder:
            parts.append(safe_folder)
        parts.append(safe_filename)
        return "/".join(parts)

    def _guess_content_type(self, filename: str) -> str:
        content_type, _ = mimetypes.guess_type(filename)
        return content_type or "application/octet-stream"

    def _build_public_url(self, object_key: str) -> str:
        if not self.public_base_url:
            raise CloudflareR2StorageError(
                "CLOUDFLARE_R2_PUBLIC_URL não configurada. "
                "Habilite a URL pública do bucket no painel Cloudflare."
            )
        encoded_key = urllib.parse.quote(object_key, safe="/")
        return f"{self.public_base_url}/{encoded_key}"

    def _read_content(self, file_obj: FileLike) -> bytes:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        content = file_obj.read()
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not content:
            raise CloudflareR2StorageError("Arquivo vazio — upload cancelado.")
        return content

    def upload_file(self, file_obj: FileLike, folder_name: str, filename: str) -> str:
        """
        Envia arquivo ao R2 e retorna URL pública de acesso direto.
        """
        object_key = self._build_object_key(folder_name, filename)
        content = self._read_content(file_obj)
        content_type = self._guess_content_type(filename)

        logger.info("[R2] Upload: %s (%s bytes)", object_key, len(content))
        try:
            self._client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=content,
                ContentType=content_type,
            )
        except ClientError as exc:
            error = exc.response.get("Error", {})
            raise CloudflareR2StorageError(
                f"Erro no upload R2 ({error.get('Code', 'unknown')}): {error.get('Message', exc)}"
            ) from exc

        public_url = self._build_public_url(object_key)
        logger.info("[R2] Upload concluído: %s", public_url[:120])
        return public_url

    def upload_file_and_get_download_url(
        self, file_obj: FileLike, folder_name: str, filename: str
    ) -> str:
        """
        Compatível com o antigo OneDriveUploader: retorna URL direta para download/visualização.
        No R2, o comportamento é o mesmo de upload_file().
        """
        return self.upload_file(file_obj, folder_name, filename)


def sanitize_r2_folder_name(value: str, max_length: int = 80) -> str:
    """Normaliza nome de pasta para uso seguro no R2."""
    cleaned = re.sub(r"[^\w\s\-_.]", "", str(value or "")).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "pasta")[:max_length]
