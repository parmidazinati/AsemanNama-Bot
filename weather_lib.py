#!/usr/bin/env python3
"""توابع مشترک هواشناسی — بدون وابستگی به کتابخانه تلگرام."""
import datetime as _dt
import json
import logging
import os

import requests

log = logging.getLogger("weather")

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, "users.json")
OFFSET_FILE = os.path.join(BASE, "offset.txt")

WEATHER_FA = {
    0: ("صاف", "☀️"),
    1: ("کمی ابری", "🌤️"),
    2: ("نیمه‌ابری", "⛅"),
    3: ("ابری", "☁️"),
    45: ("مه‌آلود", "🌫️"),
    48: ("مه یخ‌زده", "🌫️"),
    51: ("نم‌نم باران", "🌦️"),
    53: ("نم‌نم باران", "🌦️"),
    55: ("نم‌نم باران", "🌦️"),
    56: ("باران یخ‌زده", "🌧️"),
    57: ("باران یخ‌زده", "🌧️"),
    61: ("باران خفیف", "🌧️"),
    63: ("باران", "🌧️"),
    65: ("باران شدید", "🌧️"),
    66: ("باران یخ‌زده", "🌧️"),
    67: ("باران یخ‌زده شدید", "🌧️"),
    71: ("برف خفیف", "🌨️"),
    73: ("برف", "❄️"),
    75: ("برف شدید", "❄️"),
    77: ("دانه‌های برف", "🌨️"),
    80: ("رگبار خفیف", "🌦️"),
    81: ("رگبار", "🌧️"),
    82: ("رگبار شدید", "⛈️"),
    85: ("برف", "🌨️"),
    86: ("برف شدید", "🌨️"),
    95: ("رعد و برق", "⛈️"),
    96: ("رعد و برق با تگرگ", "⛈️"),
    99: ("رعد و برق با تگرگ شدید", "⛈️"),
}

WEEKDAY_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

WELCOME = (
    "سلام! 🌤️ من ربات هواشناسی‌ام.\n\n"
    "اسم شهرت رو بفرست (مثلاً: تهران، اصفهان، رشت)\n"
    "یا لوکیشنت رو برام بفرست 📍\n\n"
    "بعدش هر روز صبح ساعت ۷ هواشناسی امروز و فردای شهرت رو خودکار برات می‌فرستم."
)


def get_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return token
    try:
        with open(os.path.join(BASE, ".env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return ""


def fa_weekday(date_str: str) -> str:
    d = _dt.date.fromisoformat(date_str)
    return WEEKDAY_FA[d.weekday()]


def load_users() -> dict:
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_users(users: dict) -> None:
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def set_user_city(chat_id: int, name: str, lat: float, lon: float,
                 username: str | None = None, first_name: str | None = None) -> None:
    import datetime as _dt

    users = load_users()
    key = str(chat_id)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    prev = users.get(key) or {}
    users[key] = {
        "name": name,
        "lat": lat,
        "lon": lon,
        "first_seen": prev.get("first_seen", now),
        "last_seen": now,
        "username": username or prev.get("username"),
        "first_name": first_name or prev.get("first_name"),
    }
    save_users(users)


def touch_user(chat_id: int, username: str | None = None,
               first_name: str | None = None) -> None:
    """به‌روزرسانی آخرین فعالیت کاربر (و یوزرنیم در صورت تغییر)."""
    import datetime as _dt

    users = load_users()
    key = str(chat_id)
    if key not in users:
        return
    users[key]["last_seen"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    if username:
        users[key]["username"] = username
    if first_name:
        users[key]["first_name"] = first_name
    save_users(users)


def normalize_fa(text: str) -> str:
    """یکدست‌سازی متن فارسی/عربی برای جستجوی بهتر شهر."""
    import re

    t = text.strip()
    t = (
        t.replace("ي", "ی")
        .replace("ك", "ک")
        .replace("ؤ", "و")
        .replace("ة", "ه")
        .replace("ـ", "")
        .replace("‌", " ")  # نیم‌فاصله -> فاصله
    )
    t = re.sub(r"[\u064B-\u0652\u0670]", "", t)  # اعراب
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def geocode_open_meteo(query: str):
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 5, "language": "fa", "format": "json"},
            timeout=20,
        ).json()
    except Exception as e:  # noqa: BLE001
        log.warning("open-meteo geocode failed: %s", e)
        return None
    results = r.get("results") or []
    if not results:
        return None
    ir = [g for g in results if g.get("country_code") == "IR"]
    g = (ir or results)[0]
    return g["name"], g["latitude"], g["longitude"]


def geocode_nominatim(query: str):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "json",
                "countrycodes": "ir",
                "limit": 5,
                "accept-language": "fa",
            },
            headers={"User-Agent": "AsemanNamaBot/1.0 (Telegram weather bot)"},
            timeout=20,
        ).json()
    except Exception as e:  # noqa: BLE001
        log.warning("nominatim geocode failed: %s", e)
        return None
    if not r:
        return None

    def score(g):
        t = f"{g.get('class') or ''} {g.get('type') or ''}"
        good = ("administrative", "city", "town", "village", "county", "state", "suburb")
        return 0 if any(k in t for k in good) else 1

    g = sorted(r, key=score)[0]
    name = (g.get("display_name") or "").split(",")[0].strip()
    try:
        return (name or query), float(g["lat"]), float(g["lon"])
    except (TypeError, ValueError):
        return None


def geocode(query: str):
    """نام شهر (فارسی/انگلیسی) -> (name, lat, lon) یا None.

    اول Open-Meteo، بعد Nominatim. متن فارسی نرمال‌سازی می‌شود.
    """
    q = normalize_fa(query)
    if not q:
        return None
    variants = list(dict.fromkeys([q, q.replace(" ", "")]))
    for variant in variants:
        hit = geocode_open_meteo(variant)
        if hit:
            return hit
    for variant in variants:
        hit = geocode_nominatim(variant)
        if hit:
            return hit
    return None


def get_forecast(lat: float, lon: float, days: int = 3):
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weathercode",
                "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Asia/Tehran",
                "forecast_days": days,
            },
            timeout=20,
        ).json()
    except Exception as e:  # noqa: BLE001
        log.warning("forecast failed: %s", e)
        return None
    return r


def describe(code: int) -> str:
    text, emoji = WEATHER_FA.get(code, ("نامشخص", "🌡️"))
    return f"{emoji} {text}"


def day_block(date_str: str, code: int, tmax: float, tmin: float, pop) -> str:
    pop_txt = f" | احتمال بارش: {pop}٪" if pop is not None else ""
    return (
        f"📅 {fa_weekday(date_str)} ({date_str})\n"
        f"{describe(code)}\n"
        f"🌡️ بیشینه: {round(tmax)}° | کمینه: {round(tmin)}°{pop_txt}"
    )


def forecast_text(city: str, data: dict, days: int = 2) -> str:
    daily = data["daily"]
    parts = [f"🌤️ هواشناسی {city}"]
    for i in range(min(days, len(daily["time"]))):
        parts.append(
            day_block(
                daily["time"][i],
                daily["weathercode"][i],
                daily["temperature_2m_max"][i],
                daily["temperature_2m_min"][i],
                daily["precipitation_probability_max"][i],
            )
        )
    cur = data.get("current")
    if cur:
        parts.append(f"الان: {round(cur['temperature_2m'])}° و {describe(cur['weathercode'])}")
    return "\n\n".join(parts)
