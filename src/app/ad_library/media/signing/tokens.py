from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from uuid import UUID

from ..exceptions import MediaTokenError
from ..models import MediaKind
from .policy import MediaSigningPolicy

_TOKEN_RE = re.compile(r"(\d{1,12})\.([A-Za-z0-9_-]{43})\Z")


class MediaURLSigner:
    def __init__(self, policy: MediaSigningPolicy) -> None:
        self._policy = policy
        self._secret = policy.secret.encode()

    @property
    def ttl_seconds(self) -> int:
        return self._policy.ttl_seconds

    def url_for(
        self,
        ad_id: UUID,
        kind: MediaKind,
        stored_reference: str | None,
        *,
        now: int | None = None,
    ) -> str | None:
        if not stored_reference:
            return None
        token = self.create_token(ad_id, kind, now=now)
        public_path = self._policy.public_path.rstrip("/")
        return f"{public_path}/ads/{ad_id}/{kind.value}?token={token}"

    def create_token(
        self,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> str:
        issued_at = int(time.time()) if now is None else int(now)
        expires_at = issued_at + self._policy.ttl_seconds
        return f"{expires_at}.{self._signature(ad_id, kind, expires_at)}"

    def verify_token(
        self,
        token: str,
        ad_id: UUID,
        kind: MediaKind,
        *,
        now: int | None = None,
    ) -> int:
        match = _TOKEN_RE.fullmatch(token)
        if match is None:
            raise MediaTokenError("invalid media token")
        expires_at = int(match.group(1))
        current = int(time.time()) if now is None else int(now)
        if expires_at < current:
            raise MediaTokenError("expired media token")
        maximum = current + self._policy.ttl_seconds + self._policy.clock_skew_seconds
        if expires_at > maximum:
            raise MediaTokenError("media token expiry exceeds the configured limit")
        expected = self._signature(ad_id, kind, expires_at)
        if not hmac.compare_digest(match.group(2), expected):
            raise MediaTokenError("invalid media token")
        return expires_at

    def _signature(self, ad_id: UUID, kind: MediaKind, expires_at: int) -> str:
        payload = f"v1\n{ad_id}\n{kind.value}\n{expires_at}".encode()
        digest = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
