"""Phase 1: the generated DPoP token must verify with plain ``cryptography``.

01 §1.2 lists the encoding rules that actually matter. The padding tests loop because
an unpadded coordinate is only 31 bytes about 1 time in 256 — a single sample would
pass with a broken implementation.
"""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from carimer.transport.dpop import DpopSigner, generate_key

URL = "https://api.mercari.jp/v2/entities:search"


def _decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _parts(token: str) -> tuple[dict, dict, bytes]:
    head, payload, signature = token.split(".")
    return json.loads(_decode(head)), json.loads(_decode(payload)), _decode(signature)


def test_token_signature_verifies() -> None:
    signer = DpopSigner()
    token = signer.sign("POST", URL)
    header, payload, signature = _parts(token)
    signing_input = ".".join(token.split(".")[:2]).encode()
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    der = utils.encode_dss_signature(r, s)
    signer.key.public_key().verify(der, signing_input, ec.ECDSA(hashes.SHA256()))

    assert header["typ"] == "dpop+jwt"
    assert header["alg"] == "ES256"
    assert header["jwk"]["crv"] == "P-256"
    assert header["jwk"]["kty"] == "EC"
    assert payload["htu"] == URL
    assert payload["htm"] == "POST"
    assert "iat" in payload and "jti" in payload


def test_method_is_upcased_and_htu_keeps_the_query_string() -> None:
    url = "https://api.mercari.jp/items/get?id=m123&include_auction=true"
    _, payload, _ = _parts(DpopSigner().sign("get", url))
    assert payload["htm"] == "GET"
    assert payload["htu"] == url


def test_coordinates_and_signature_halves_are_padded_to_32_bytes() -> None:
    for _ in range(64):
        signer = DpopSigner(generate_key())
        header, _, signature = _parts(signer.sign("POST", URL))
        assert len(_decode(header["jwk"]["x"])) == 32
        assert len(_decode(header["jwk"]["y"])) == 32
        assert len(signature) == 64


def test_device_uuid_claim_is_optional() -> None:
    _, without, _ = _parts(DpopSigner().sign("POST", URL))
    assert "uuid" not in without
    _, with_uuid, _ = _parts(DpopSigner(device_uuid="dev-1").sign("POST", URL))
    assert with_uuid["uuid"] == "dev-1"


def test_jti_is_unique_per_token() -> None:
    signer = DpopSigner()
    jtis = {_parts(signer.sign("POST", URL))[1]["jti"] for _ in range(5)}
    assert len(jtis) == 5


def test_rotate_every_replaces_the_key() -> None:
    signer = DpopSigner(rotate_every=2)
    first = signer.public_jwk()
    signer.sign("POST", URL)
    assert signer.public_jwk() == first  # 1 signature: same key
    signer.sign("POST", URL)
    assert signer.public_jwk() == first
    signer.sign("POST", URL)  # 3rd signature rotates first
    assert signer.public_jwk() != first


def test_rotate_every_zero_never_rotates() -> None:
    signer = DpopSigner()
    first = signer.public_jwk()
    for _ in range(5):
        signer.sign("POST", URL)
    assert signer.public_jwk() == first


def test_negative_rotate_every_rejected() -> None:
    with pytest.raises(ValueError, match="rotate_every"):
        DpopSigner(rotate_every=-1)
