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
    mongo_database: str = "tinyurl"
    cassandra_host: str = "localhost"
    cassandra_port: int = 9043
    # Name of the Cassandra data center this app talks to ("datacenter1" is what a
    # fresh single-node Cassandra calls itself).
    cassandra_local_dc: str = "datacenter1"

    # Signs every login token, so whoever holds it can forge a token for any
    # user. Deliberately has NO default: the app refuses to start without one,
    # instead of silently running with a key that anyone reading the code knows.
    jwt_secret: str
    jwt_expire_minutes: int = 60

    # Rate limits (sliding window). Creating links is limited per user; redirects
    # per client IP, generously, because an office or school shares one address.
    create_link_limit: int = 20
    create_link_window_seconds: int = 60
    redirect_limit: int = 120
    redirect_window_seconds: int = 60
    # Login attempts per client IP: slows down password guessing.
    login_limit: int = 10
    login_window_seconds: int = 60

    # Name of this worker inside the consumer group. Run several workers by
    # giving each its own name. A restarted worker keeping its name picks up
    # right where it left off.
    worker_name: str = "worker-1"

    # Public address of this service, used to build the short links we return.
    base_url: str = "http://localhost:8001"


settings = Settings()
