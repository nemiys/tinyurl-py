#!/bin/sh
# Runs before the real command (uvicorn or the worker).
#
# The app refuses to start without JWT_SECRET: a key that anyone reading the
# repository knows would let anyone forge a login token. For a one-command demo
# we do not want to make the visitor invent one either, so when none is given
# we make a random one for this run.
#
# Consequence: tokens stop working when the container restarts. For anything
# beyond a demo, set JWT_SECRET (see .env.example).
set -e

if [ -z "$JWT_SECRET" ]; then
  JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  export JWT_SECRET
  echo "JWT_SECRET is not set: using a random one for this run (logins end on restart)."
fi

exec "$@"
