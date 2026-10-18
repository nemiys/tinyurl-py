"""Centralized configuration.

Defaults point at the host-mapped Docker ports from docker-compose.yml, so a
normal local run needs no setup. Every value can be overridden through an
environment variable (or a local `.env` file, which is git-ignored), which is
what we will do once the app itself runs inside a container: there,
"localhost:6381" reaches nothing, and the right address is the service name.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Host ports are deliberately non-default so this project can run next to
    # wikiguard-py (Redis 6380) and the old nemiys-tinyurl (6379, 27017, 9042).
    redis_url: str = "redis://localhost:6381"
    mongo_url: str = "mongodb://localhost:27018"
    cassandra_host: str = "localhost"
    cassandra_port: int = 9043


settings = Settings()
