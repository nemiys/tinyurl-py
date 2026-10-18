"""Shared FastAPI dependencies.

A dependency is something an endpoint asks for as a parameter and FastAPI
supplies. Endpoints therefore never fetch their own database, which also lets
tests swap in a test database (`app.dependency_overrides`).
"""

from typing import Annotated, Any

from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from tinyurl_py.persistence.mongo import DATABASE_NAME


def get_db(request: Request) -> AsyncDatabase[dict[str, Any]]:
    # The client was created once at startup (see `lifespan` in main.py).
    db: AsyncDatabase[dict[str, Any]] = request.app.state.mongo[DATABASE_NAME]
    return db


# Endpoints write `db: Database` and get the object above.
Database = Annotated[AsyncDatabase[dict[str, Any]], Depends(get_db)]
