"""Registration and login."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError

from tinyurl_py.api.dependencies import Database, limit_login, limit_registration
from tinyurl_py.api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from tinyurl_py.security.passwords import hash_password, verify_password
from tinyurl_py.security.tokens import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

# A real hash of a throwaway password. Used when the email is unknown so that
# login still does one full (slow) verification: otherwise "unknown email"
# would answer in milliseconds and "wrong password" in ~60 ms, and that timing
# difference would reveal which emails are registered.
_DUMMY_HASH = hash_password("a-password-nobody-has")


@router.post(
    "/register",
    status_code=201,
    response_model=UserPublic,
    dependencies=[Depends(limit_registration)],
    responses={
        409: {"description": "This email is already registered"},
        429: {"description": "Too many sign-ups from this address; see Retry-After"},
    },
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


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(limit_login)],
    responses={
        401: {"description": "Wrong email or password"},
        429: {"description": "Too many attempts from this address; see Retry-After"},
    },
)
async def login(body: LoginRequest, db: Database) -> TokenResponse:
    user = await db.users.find_one({"email": body.email.lower()})

    stored_hash = user["password_hash"] if user is not None else _DUMMY_HASH
    password_ok = await asyncio.to_thread(verify_password, body.password, stored_hash)

    if user is None or not password_ok:
        # One message for both cases, so the answer never says which part was wrong.
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(access_token=create_access_token(str(user["_id"])))
