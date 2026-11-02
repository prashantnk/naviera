"""
`Idempotency-Key` support for money POSTs (H-4, plan B13).

A client sends `Idempotency-Key: <uuid>` on a money request. The first request with
that key claims it (row in `idempotency_keys`, response NULL) and runs; when it
succeeds the endpoint stores its response. A retry with the same key and the same
request body gets the stored response back without running again; the same key with
a different body is refused (422); a retry while the first one is still running gets
409. If the guarded request fails, the claim is released so the client may retry.

Claims and stored responses use their own short-lived session, so they never mix with
the request's unit of work (Spring analogy: an idempotent-receiver filter backed by a
unique-key table, with `REQUIRES_NEW` transactions for the key bookkeeping).

Usage in a controller:

    idem: IdempotencyContext = Depends(require_idempotency("shipments.measurements"))
    if idem.replay is not None:
        return idem.replay
    result = await service.do_money_thing()
    body = SomeRead.model_validate(result)
    await idem.store(body)
    return body
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core import db as db_module
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.repricing import IDEMPOTENCY_KEY_MAX_LENGTH, IdempotencyKey
from app.models.tenants import Tenant, User
from app.repositories.repricing import IdempotencyRepository

IDEMPOTENCY_HEADER = "Idempotency-Key"
"""Request header carrying the client-generated key."""

REPLAY_HEADER = "Idempotency-Replayed"
"""Response header set on a replayed response."""

RESPONSE_STATUS_KEY = "status_code"
RESPONSE_BODY_KEY = "body"

KEY_REUSED_DETAIL = "This Idempotency-Key was already used for a different request."
IN_FLIGHT_DETAIL = "A request with this Idempotency-Key is still being processed. Retry shortly."
KEY_REQUIRED_DETAIL = f"The {IDEMPOTENCY_HEADER} header is required for this request."
KEY_TOO_LONG_DETAIL = f"{IDEMPOTENCY_HEADER} must be at most {IDEMPOTENCY_KEY_MAX_LENGTH} characters."


def compute_request_hash(method: str, path: str, query: str, body: bytes) -> str:
    """
    SHA-256 fingerprint of a request: method, path, query string and canonical body.

    JSON bodies are re-serialized with sorted keys so whitespace / key order do not
    change the hash; other bodies are hashed as raw bytes.

    Returns:
        64 lowercase hex characters.
    """
    try:
        canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode()
    except (ValueError, UnicodeDecodeError):
        canonical = body or b""
    digest = hashlib.sha256()
    for part in (method.upper().encode(), path.encode(), query.encode(), canonical):
        digest.update(part)
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass
class IdempotencyContext:
    """What the dependency hands to the endpoint."""

    endpoint: str
    key: Optional[str]
    request_hash: str
    tenant_id: Optional[uuid.UUID] = None
    replay: Optional[JSONResponse] = None
    claim_id: Optional[uuid.UUID] = None
    stored: bool = field(default=False)

    async def store(self, payload: Any, status_code: int = status.HTTP_200_OK) -> None:
        """
        Saves the successful response under the claimed key (no-op without a key).

        Args:
            payload: Anything `jsonable_encoder` accepts (Pydantic model, dict, list).
            status_code: The HTTP status the endpoint returns.
        """
        if self.claim_id is None or self.stored:
            return
        response = {RESPONSE_STATUS_KEY: status_code, RESPONSE_BODY_KEY: jsonable_encoder(payload)}
        async with db_module.AsyncSessionLocal() as session:  # type: ignore[attr-defined]
            row = await session.get(IdempotencyKey, self.claim_id)
            if row is not None:
                row.response = response
                session.add(row)
                await session.commit()
        self.stored = True

    async def release(self) -> None:
        """Deletes an unfinished claim so the client may retry."""
        if self.claim_id is None or self.stored or self.tenant_id is None:
            return
        async with db_module.AsyncSessionLocal() as session:  # type: ignore[attr-defined]
            await IdempotencyRepository(session).delete(tenant_id=self.tenant_id, row_id=self.claim_id)
            await session.commit()
        self.claim_id = None


def _replay_response(row: IdempotencyKey) -> JSONResponse:
    """The stored response, marked as a replay."""
    stored = row.response or {}
    return JSONResponse(
        status_code=int(stored.get(RESPONSE_STATUS_KEY, status.HTTP_200_OK)),
        content=stored.get(RESPONSE_BODY_KEY),
        headers={REPLAY_HEADER: "true"},
    )


def _validate_key(raw: Optional[str], required: bool) -> Optional[str]:
    """Normalizes the header value; 400 when required and missing, 422 when too long."""
    key = (raw or "").strip() or None
    if key is None and required:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=KEY_REQUIRED_DETAIL)
    if key is not None and len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=KEY_TOO_LONG_DETAIL)
    return key


async def claim_or_replay(context: IdempotencyContext, user_id: uuid.UUID) -> None:
    """
    Claims `context.key` for this tenant/user/endpoint, or loads the stored replay.

    Raises:
        HTTPException(422): same key, different request body.
        HTTPException(409): same key, first request still in flight (or a concurrent claim).
    """
    async with db_module.AsyncSessionLocal() as session:  # type: ignore[attr-defined]
        repo = IdempotencyRepository(session)
        existing = await repo.get(
            tenant_id=context.tenant_id, user_id=user_id, endpoint=context.endpoint, key=context.key
        )
        if existing is not None:
            _check_existing(existing, context)
            context.replay = _replay_response(existing)
            return
        row = IdempotencyKey(
            tenant_id=context.tenant_id,
            user_id=user_id,
            endpoint=context.endpoint,
            key=context.key,
            request_hash=context.request_hash,
        )
        try:
            await repo.add(row)
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=IN_FLIGHT_DETAIL) from exc
        context.claim_id = row.id


def _check_existing(existing: IdempotencyKey, context: IdempotencyContext) -> None:
    """422 on a body mismatch, 409 while the first request has no stored response."""
    if existing.request_hash != context.request_hash:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=KEY_REUSED_DETAIL)
    if existing.response is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=IN_FLIGHT_DETAIL)


def require_idempotency(
    endpoint: str, *, required: bool = False
) -> Any:
    """
    Builds the FastAPI dependency for one money endpoint.

    Args:
        endpoint: Stable logical name, e.g. "shipments.measurements" (part of the key scope).
        required: Reject requests without the header (400) instead of running unguarded.

    Returns:
        An async-generator dependency yielding an IdempotencyContext.
    """

    async def _dependency(
        request: Request,
        current_user: User = Depends(get_current_active_user),
        current_tenant: Tenant = Depends(get_tenant_from_header),
    ) -> AsyncIterator[IdempotencyContext]:
        key = _validate_key(request.headers.get(IDEMPOTENCY_HEADER), required)
        body = await request.body()
        context = IdempotencyContext(
            endpoint=endpoint,
            key=key,
            request_hash=compute_request_hash(request.method, request.url.path, request.url.query, body),
            tenant_id=current_tenant.id,
        )
        if key is None:
            yield context
            return
        await claim_or_replay(context, current_user.id)
        if context.replay is not None:
            yield context
            return
        try:
            yield context
        except Exception:
            await context.release()
            raise
        if not context.stored:
            await context.release()

    return _dependency
