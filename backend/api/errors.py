# -*- coding: utf-8 -*-
"""Mapping service-layer failures onto HTTP status codes.

The distinctions are deliberate, because a client can only respond sensibly to a
failure it can tell apart from the others:

    404  the conversation or case does not exist
    409  it exists, but the operation does not apply to its current state — a
         representative reply while nobody has taken over
    400  the request was understood and its content was wrong, such as a cursor that
         is neither a message id nor a timestamp
    422  the request could not be parsed against its model at all

Collapsing 409 into 400, or 400 into 422, would leave a frontend guessing whether to
retry, to fix the input, or to tell the user something has changed underneath them.
"""
from __future__ import annotations


def not_found(detail: str):
    from fastapi import HTTPException

    return HTTPException(status_code=404, detail=detail)


def conflict(detail: str):
    from fastapi import HTTPException

    return HTTPException(status_code=409, detail=detail)


def bad_request(detail: str):
    from fastapi import HTTPException

    return HTTPException(status_code=400, detail=detail)
