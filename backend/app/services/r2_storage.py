"""
PhotoCAD - Cloudflare R2 (S3-Compatible) Storage & Local Dev Fallback Service
Document ID: PCAD-SAD-002 Section 4 (Cold Storage Tier)

Generates AWS Signature Version 4 pre-signed PUT/GET URLs for direct browser-to-R2
binary transfers (.PNG keyframes, masked RGBA views, fused .PLY clouds, CAD exports)
without heavyweight boto3 dependencies. Falls back transparently to local `/storage`
files during Zero-Heat offline development when R2 keys are unconfigured.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from app.core.config import settings


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str = "auto", service: str = "s3") -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


class R2StorageService:
    """Unified cold-tier object storage interface with R2 SigV4 signing + local fallback."""

    def __init__(self) -> None:
        self.account_id = os.getenv("CLOUDFLARE_R2_ACCOUNT_ID", "")
        self.access_key = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
        self.secret_key = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
        self.bucket = os.getenv("CLOUDFLARE_R2_BUCKET_NAME", "photocad-assets")
        self.public_url = os.getenv("CLOUDFLARE_R2_PUBLIC_URL", "").rstrip("/")

    @property
    def is_r2_configured(self) -> bool:
        return bool(
            self.account_id
            and "your-cloudflare" not in self.account_id
            and self.access_key
            and "your-r2" not in self.access_key
            and self.secret_key
            and "your-r2" not in self.secret_key
        )

    def generate_presigned_url(
        self,
        object_key: str,
        method: str = "GET",
        expires_in: int = 900,
    ) -> str:
        """
        Creates a pre-signed S3/R2 URL using AWS SigV4 when R2 is configured,
        or a local API/static URL during dev mode.
        """
        clean_key = object_key.lstrip("/")
        if not self.is_r2_configured:
            # Local dev routing under FastAPI `/storage` or `/api/scans/...`
            return f"/storage/{clean_key}"

        host = f"{self.account_id}.r2.cloudflarestorage.com"
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        region = "auto"
        service = "s3"
        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"

        canonical_uri = "/" + quote(f"{self.bucket}/{clean_key}", safe="/-_.~")
        query_params = {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": f"{self.access_key}/{credential_scope}",
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires_in),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_querystring = urlencode(sorted(query_params.items()), quote_via=quote)
        canonical_headers = f"host:{host}\n"
        canonical_request = "\n".join([
            method.upper(),
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            "host",
            "UNSIGNED-PAYLOAD",
        ])

        request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            request_hash,
        ])

        k_signing = _signing_key(self.secret_key, date_stamp, region, service)
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        return f"https://{host}{canonical_uri}?{canonical_querystring}&X-Amz-Signature={signature}"

    def local_path_for_key(self, object_key: str) -> Path:
        """Maps canonical keys (`uploads/...`, `masked/...`, `exports/...`) to local storage dirs."""
        clean_key = object_key.lstrip("/")
        target = settings.STORAGE_DIR / clean_key
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def save_local_bytes(self, object_key: str, data: bytes) -> Path:
        """Persists asset bytes to local workspace storage when running in dev mode."""
        path = self.local_path_for_key(object_key)
        path.write_bytes(data)
        return path

    def read_local_bytes(self, object_key: str) -> Optional[bytes]:
        """Reads stored binary asset bytes from local storage if available."""
        path = settings.STORAGE_DIR / object_key.lstrip("/")
        if path.exists():
            return path.read_bytes()
        return None


r2_storage = R2StorageService()
