"""
Run this ONCE on your host machine (not inside Docker) to generate session.session.
Telethon needs interactive phone/OTP verification which can't happen inside a container.

Usage (with uv — no manual venv needed):
    cd osint_fastapi
    uv run --with telethon --with python-dotenv python generate_session.py

After it finishes, session.session will be created in this directory.
The docker-compose mounts it into the container automatically.
"""

import os
from dotenv import load_dotenv
from telethon.sync import TelegramClient

load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")

if not API_ID or not API_HASH:
    raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in osint_fastapi/.env first.")

print("Starting Telegram session generation...")
print("You will be prompted for your phone number and the OTP sent to your Telegram app.\n")

with TelegramClient("session", int(API_ID), API_HASH) as client:
    print(f"\nLogged in as: {client.get_me().username}")
    print("\nsession.session created successfully.")
    print("You can now start the Docker containers.")
