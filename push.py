#!/usr/bin/env python3
"""ارسال روزانه هواشناسی به کاربران — اجرا از طریق cron (فقط با متد GET)."""
import logging
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from weather_lib import forecast_text, get_forecast, get_token, load_users  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("weather-push")


def main() -> None:
    token = get_token()
    if not token:
        print("TELEGRAM_BOT_TOKEN missing", file=sys.stderr)
        sys.exit(1)
    api = f"https://api.telegram.org/bot{token}"
    users = load_users()
    log.info("pushing to %d user(s)", len(users))
    for chat_id, u in users.items():
        try:
            data = get_forecast(u["lat"], u["lon"], days=2)
            if not data or "daily" not in data:
                continue
            text = "☀️ صبح بخیر!\n\n" + forecast_text(u["name"], data, days=2)
            r = requests.get(
                f"{api}/sendMessage",
                params={"chat_id": int(chat_id), "text": text},
                timeout=30,
            ).json()
            if not r.get("ok"):
                log.warning("send to %s failed: %s", chat_id, r)
        except Exception as e:  # noqa: BLE001
            log.warning("push to %s failed: %s", chat_id, e)


if __name__ == "__main__":
    main()
