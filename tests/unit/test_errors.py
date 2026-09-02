"""Phase 1: status + body → exception mapping (01 §1.3, 03 §3.2)."""

from __future__ import annotations

import pytest

from carimer.transport import errors

LEGACY_NOT_FOUND = (
    b'{"result":"error","errors":[{"code":"RecordNotFoundException","message":"no item"}],"meta":{}}'
)
LEGACY_INVALID_ARG = b'{"result":"error","errors":[{"code":"InvalidArgument","message":"bad id"}]}'
LEGACY_UNSUPPORTED = (
    b'{"result":"error","errors":[{"code":"UnsupportedVersionException","message":"unsupported"}]}'
)
GRPC_UNAUTH = b'{"code":16,"message":"unauthorized: missing auth token","requestId":"x","details":null}'
GRPC_BAD = b'{"code":3,"message":"cannot unmarshal number into Go value of type string"}'
GRPC_NOT_FOUND = b'{"code":5,"message":"product not found"}'
TEXT_406 = b"no accepted candidate variant"
TEXT_404 = b"404 page not found"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, GRPC_UNAUTH, errors.AuthError),
        (400, GRPC_BAD, errors.BadRequestError),
        (400, LEGACY_INVALID_ARG, errors.BadRequestError),
        (400, LEGACY_UNSUPPORTED, errors.BadRequestError),
        (404, LEGACY_NOT_FOUND, errors.NotFoundError),
        (404, GRPC_NOT_FOUND, errors.NotFoundError),
        (404, TEXT_404, errors.NotFoundError),
        (406, TEXT_406, errors.NotAcceptableError),
        (403, b"", errors.BlockedError),
        (429, b"whatever", errors.RateLimitedError),
        (500, b"boom", errors.TransportError),
        (503, b"", errors.TransportError),
    ],
)
def test_status_and_body_map_to_exception(status: int, body: bytes, expected: type[Exception]) -> None:
    assert type(errors.from_response(status, {}, body)) is expected


def test_bad_request_keeps_code_and_message() -> None:
    exc = errors.from_response(400, {}, LEGACY_UNSUPPORTED)
    assert isinstance(exc, errors.BadRequestError)
    assert exc.code == "UnsupportedVersionException"
    assert "unsupported" in exc.message


def test_grpc_bad_request_keeps_numeric_code() -> None:
    exc = errors.from_response(400, {}, GRPC_BAD)
    assert isinstance(exc, errors.BadRequestError)
    assert exc.code == 3
    assert "unmarshal" in exc.message


def test_not_found_kind_is_reported() -> None:
    legacy = errors.from_response(404, {}, LEGACY_NOT_FOUND)
    grpc = errors.from_response(404, {}, GRPC_NOT_FOUND)
    unknown_path = errors.from_response(404, {}, TEXT_404)
    assert isinstance(legacy, errors.NotFoundError) and legacy.kind == "RecordNotFoundException"
    assert isinstance(grpc, errors.NotFoundError) and grpc.kind == "NotFound"
    assert isinstance(unknown_path, errors.NotFoundError) and unknown_path.kind == "UnknownPath"


def test_rate_limited_reads_retry_after() -> None:
    exc = errors.from_response(429, {"Retry-After": "12"}, b"")
    assert isinstance(exc, errors.RateLimitedError)
    assert exc.retry_after == 12.0
    assert errors.from_response(429, {"Retry-After": "Wed, 01 Jan 2031"}, b"").retry_after is None  # type: ignore[attr-defined]


def test_parse_error_body_handles_non_json_and_empty() -> None:
    assert errors.parse_error_body(TEXT_406) == (None, "no accepted candidate variant")
    assert errors.parse_error_body(None) == (None, "")
    assert errors.parse_error_body(b"[1,2]") == (None, "[1,2]")


def test_only_429_and_5xx_are_retryable() -> None:
    assert errors.is_retryable_status(429)
    assert errors.is_retryable_status(500)
    assert errors.is_retryable_status(599)
    for status in (400, 401, 403, 404, 406, 200):
        assert not errors.is_retryable_status(status)
