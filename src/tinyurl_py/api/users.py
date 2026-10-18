"""Endpoints about the logged-in user."""

from fastapi import APIRouter

from tinyurl_py.api.dependencies import CurrentUser
from tinyurl_py.api.schemas import UserPublic

router = APIRouter(tags=["users"])


@router.get(
    "/me",
    response_model=UserPublic,
    responses={401: {"description": "Missing, invalid or expired token"}},
)
async def me(user: CurrentUser) -> UserPublic:
    # Copy only the public fields; the stored document also has the password hash.
    return UserPublic(id=str(user["_id"]), email=user["email"], created_at=user["created_at"])
