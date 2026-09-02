"""DPoP token generation with ``cryptography`` only (01-api-spec.md §1.2).

The server does not register or track keys: a fresh key per request, one key for the
whole client, or even replaying the same token all return 200. Only ``htu`` (path) and
``htm`` are checked. ``iat`` and ``jti`` are not validated.

The one thing that must be exact is the encoding: ``jwk.x``/``jwk.y`` and the signature
halves ``r``/``s`` are each left-zero-padded to 32 bytes. A raw big-endian int without
padding produces a 31-byte value roughly 1 time in 256, which the server rejects.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

__all__ = ["DpopSigner", "b64url", "generate_key"]

_COORD_BYTES = 32


def b64url(data: bytes) -> str:
    """base64url without padding (JWS convention)."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _fixed_width(value: int) -> bytes:
    return value.to_bytes(_COORD_BYTES, "big")


def generate_key() -> ec.EllipticCurvePrivateKey:
    """A fresh P-256 (secp256r1) private key."""
    return ec.generate_private_key(ec.SECP256R1())


class DpopSigner:
    """Signs one ``DPoP`` header value per request.

    ``rotate_every=N`` replaces the key after N signatures (``0`` = never, the
    default). ``device_uuid`` becomes the optional ``uuid`` claim the web app sends.
    """

    def __init__(
        self,
        key: ec.EllipticCurvePrivateKey | None = None,
        *,
        device_uuid: str | None = None,
        rotate_every: int = 0,
    ) -> None:
        if rotate_every < 0:
            raise ValueError("rotate_every must be >= 0")
        self._key = key or generate_key()
        self._device_uuid = device_uuid
        self._rotate_every = rotate_every
        self._signed = 0

    @property
    def key(self) -> ec.EllipticCurvePrivateKey:
        return self._key

    @property
    def signed_count(self) -> int:
        return self._signed

    def rotate(self) -> None:
        """Replace the key immediately."""
        self._key = generate_key()

    def public_jwk(self) -> dict[str, str]:
        numbers = self._key.public_key().public_numbers()
        return {
            "crv": "P-256",
            "kty": "EC",
            "x": b64url(_fixed_width(numbers.x)),
            "y": b64url(_fixed_width(numbers.y)),
        }

    def sign(self, method: str, url: str, *, iat: int | None = None) -> str:
        """Return the ``DPoP`` header value for ``method``/``url``.

        ``url`` is the final URL including the query string, matching the web app. The
        server compares only the path (01 §1.2), but there is no reason to differ.
        """
        if self._rotate_every and self._signed and self._signed % self._rotate_every == 0:
            self.rotate()
        header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": self.public_jwk()}
        payload: dict[str, Any] = {
            "iat": int(time.time()) if iat is None else iat,
            "jti": str(uuid.uuid4()),
            "htu": url,
            "htm": method.upper(),
        }
        if self._device_uuid:
            payload["uuid"] = self._device_uuid
        signing_input = f"{b64url(_compact(header))}.{b64url(_compact(payload))}"
        der = self._key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        signature = b64url(_fixed_width(r) + _fixed_width(s))
        self._signed += 1
        return f"{signing_input}.{signature}"


def _compact(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
