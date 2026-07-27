#!/usr/bin/env bash
# Push the working tree to the server and restart. Run from the repo root.
set -euo pipefail

HOST="${CRWARBOT_HOST:?set CRWARBOT_HOST=user@host}"
STAGE=/tmp/crwarbot-src
TARGET=/opt/crwarbot

rsync -az --delete \
    --exclude '.venv' --exclude '.git' --exclude 'docs' --exclude '__pycache__' \
    --exclude '.pytest_cache' --exclude '.ruff_cache' --exclude '*.db*' --exclude '.env' \
    ./ "$HOST:$STAGE/"

# .venv and .env live in the target and must survive --delete.
ssh "$HOST" "set -e
    sudo -n rsync -a --delete --exclude .venv --exclude .env --exclude '*.db*' $STAGE/ $TARGET/
    sudo -n chown -R crwarbot:crwarbot $TARGET
    sudo -n -u crwarbot $TARGET/.venv/bin/pip install -q -e $TARGET
    sudo -n systemctl restart crwarbot
    sleep 3
    sudo -n systemctl is-active crwarbot"
