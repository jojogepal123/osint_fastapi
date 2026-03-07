#!/bin/sh
set -e

# If GHUNT_KEYS_JSON is set in .env, write it to the credentials file
# so you don't need to run `ghunt login` interactively inside the container.
#
# How to get the value:
#   1. Run `ghunt login` once interactively
#   2. Copy the contents of /ghunt-creds/ (or wherever GHUNT_ENVIRONMENT_PATH points)
#   3. Paste the JSON content as GHUNT_KEYS_JSON in osint_fastapi/.env
if [ -n "$GHUNT_KEYS_JSON" ]; then
    mkdir -p "$GHUNT_ENVIRONMENT_PATH"
    printf '%s' "$GHUNT_KEYS_JSON" > "$GHUNT_ENVIRONMENT_PATH/ghunt_keys.json"
    echo "[entrypoint] GHunt credentials written from GHUNT_KEYS_JSON"
fi

exec "$@"
