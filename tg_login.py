"""One-time Telegram login for the EGX signal follower (Ahmed types phone + code himself).

Needs TG_API_ID / TG_API_HASH in .env (from https://my.telegram.org → API development tools).
Run:  python tg_login.py   → creates tg_egx.session (gitignored). Then lists your groups so we pick which to follow.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon.sync import TelegramClient

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

with TelegramClient(str(HERE / "tg_egx"), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"]) as client:
    me = client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username})\n\nYour groups/channels:")
    for d in client.iter_dialogs():
        if d.is_group or d.is_channel:
            print(f"{d.id}\t{d.name}")
