# Deploy

The Supercell API token is bound to the IP address that requests it, so generate
the token on developer.clashroyale.com **from the server's IP**, not from your
laptop.

## Install

```bash
sudo useradd -r -m -d /opt/crwarbot crwarbot
sudo -u crwarbot git clone <repo> /opt/crwarbot
cd /opt/crwarbot
sudo -u crwarbot python3.12 -m venv .venv
sudo -u crwarbot .venv/bin/pip install -e .
sudo -u crwarbot cp .env.example .env
sudo -u crwarbot ${EDITOR:-vi} .env
```

`TELEGRAM_CHAT_ID` is the group's id, including the leading `-100`. Add the bot
to the group first, then read the id from any update (or use `@RawDataBot`).

## Run

```bash
sudo cp deploy/crwarbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crwarbot
journalctl -u crwarbot -f
```

## Backups

`data.db` holds everything. Snapshot it with the online backup API so a WAL
checkpoint mid-copy cannot corrupt the file:

```bash
sqlite3 /opt/crwarbot/data.db ".backup '/opt/crwarbot/backups/data-$(date +%F).db'"
```

Wire that into a daily cron or systemd timer.

## Upgrade

```bash
cd /opt/crwarbot
sudo -u crwarbot git pull
sudo -u crwarbot .venv/bin/pip install -e .
sudo systemctl restart crwarbot
```

Migrations apply on startup, so no separate step.
