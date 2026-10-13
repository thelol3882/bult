"""Cursor helpers."""


def test_cursor_roundtrip():
    # encode_cursor(dt, "d1") → decode_cursor → (dt, "d1") exactly (timezone kept)
    raise NotImplementedError


def test_bad_cursor_is_422():
    # GET /apps/x/deploys?cursor=not-base64 → 422 with code invalid_cursor
    raise NotImplementedError
