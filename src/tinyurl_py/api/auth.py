"""Registration and login."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from tinyurl_py.api.dependencies import Database
from tinyurl_py.api.schemas import RegisterRequest, UserPublic
from tinyurl_py.security.passwords import hash_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=201,
    response_model=UserPublic,
    responses={409: {"description": "This email is already registered"}},
)
async def register(body: RegisterRequest, db: Database) -> UserPublic:
    # "Dana@Example.com" and "dana@example.com" are the same person; storing
    # one canonical form lets the unique index on `email` catch both.
    email = body.email.lower()

    # argon2 is slow and blocking: run it on a helper thread so the server can
    # keep answering other requests meanwhile.
    password_hash = await asyncio.to_thread(hash_password, body.password)

    created_at = datetime.now(UTC)
    try:
        result = await db.users.insert_one(
            {"email": email, "password_hash": password_hash, "created_at": created_at}
        )
    except DuplicateKeyError as error:
        # The unique index decides, so two simultaneous sign-ups cannot both win.
        # Trade-off: this reveals that the email exists. Fine for this project;
        # a stricter service would answer the same way in both cases.
        raise HTTPException(status_code=409, detail="Email already registered") from error

    return UserPublic(id=str(result.inserted_id), email=email, created_at=created_at)
