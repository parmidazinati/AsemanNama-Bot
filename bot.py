#!/usr/bin/env python3
"""ربات هواشناسی تلگرام — long-polling با متد GET (سازگار با محدودیت پروکسی)."""
import json
import logging
import os
import sys
import threading
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from weather_lib import (  # noqa: E402
    OFFSET_FILE,
    WELCOME,
    day_block,
    forecast_text,
    geocode,
    get_forecast,
    get_token,
    load_users,
    log,
    set_user_city,
    touch_user,
)
from card import make_weather_card, make_week_card  # noqa: E402
from gshot import GoogleShotError, google_weather_shot, google_weather_text  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TOKEN = get_token()
if not TOKEN:
    print("TELEGRAM_BOT_TOKEN missing", file=sys.stderr)
    sys.exit(1)
API = f"https://api.telegram.org/bot{TOKEN}"


def api(method: str, **params):
    r = requests.get(f"{API}/{method}", params=params, timeout=45)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram api error: {data}")
    return data["result"]


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
    params = {"chat_id": chat_id, "text": text}
    # دکمه‌های اصلی همیشه باشند تا نپرند؛ فقط وقتی inline-keyboard صریح داده شد همان می‌ماند
    if reply_markup is None:
        reply_markup = KEYBOARD
    params["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return api("sendMessage", **params)


BTN_TODAY = "🌤️ هواشناسی امروز"
BTN_TOMORROW = "🌧️ هواشناسی فردا"
BTN_WEEK = "📊 پیش‌بینی ۷ روزه"
BTN_CITY = "📍 تغییر شهر"

KEYBOARD = {
    "keyboard": [
        [{"text": BTN_TODAY}, {"text": BTN_TOMORROW}],
        [{"text": BTN_WEEK}, {"text": BTN_CITY}],
    ],
    "resize_keyboard": True,
}


def _chat_action_loop(chat_id: int, stop: threading.Event, action: str):
    while not stop.wait(4):
        try:
            api("sendChatAction", chat_id=chat_id, action=action)
        except Exception:  # noqa: BLE001
            pass


class loading:
    """نمایش حالت لودینگ تلگرام (مثلاً «در حال ارسال عکس...») تا پایان کار."""

    def __init__(self, chat_id: int, action: str = "upload_photo"):
        self.chat_id = chat_id
        self.action = action
        self._stop = threading.Event()

    def __enter__(self):
        try:
            api("sendChatAction", chat_id=self.chat_id, action=self.action)
        except Exception:  # noqa: BLE001
            pass
        threading.Thread(
            target=_chat_action_loop,
            args=(self.chat_id, self._stop, self.action),
            daemon=True,
        ).start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        return False


class ProgressBar:
    """نوار پیشرفت پرشونده با ویرایش پیام — برای کارهای طولانی مثل اسکرین‌شات."""

    def __init__(self, chat_id: int, text: str):
        self.chat_id = chat_id
        self.text = text
        self._stop = threading.Event()
        self._t = None
        self.mid = None

    def _render(self, pct: int) -> str:
        n = 10
        filled = min(n, int(pct / 100 * n))
        bar = "▓" * filled + "░" * (n - filled)
        return f"{self.text}\n{bar} {pct}٪"

    def _loop(self):
        for pct in (8, 16, 26, 36, 46, 56, 66, 74, 82, 88):
            if self._stop.wait(1.4):
                return
            try:
                api("editMessageText", chat_id=self.chat_id,
                    message_id=self.mid, text=self._render(pct))
            except Exception:  # noqa: BLE001
                pass
        self._stop.wait()  # نگه داشتن روی ۸۸٪ تا پایان کار

    def __enter__(self):
        r = send_message(self.chat_id, self._render(3))
        self.mid = (r or {}).get("message_id")
        if self.mid:
            self._t = threading.Thread(target=self._loop, daemon=True)
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(timeout=4)
        if self.mid:
            try:
                api("editMessageText", chat_id=self.chat_id,
                    message_id=self.mid, text=self._render(100))
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.7)
            _drop_interim(self.chat_id, self.mid)
        return False


def send_photo(chat_id: int, photo_path: str, caption: str = "",
             reply_markup: dict | None = None) -> dict:
    if reply_markup is None:
        reply_markup = KEYBOARD
    with open(photo_path, "rb") as f:
        r = requests.post(
            f"{API}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption,
                  "reply_markup": json.dumps(reply_markup, ensure_ascii=False)},
            files={"photo": ("card.png", f, "image/png")},
            timeout=60,
        )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram api error: {data}")
    return data["result"]


def edit_message(chat_id: int, message_id: int, text: str) -> dict:
    return api("editMessageText", chat_id=chat_id, message_id=message_id, text=text)


def load_offset() -> int:
    try:
        with open(OFFSET_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def save_offset(offset: int) -> None:
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))


def get_user(chat_id: int):
    return load_users().get(str(chat_id))


def _drop_interim(chat_id: int, mid: int):
    try:
        api("deleteMessage", chat_id=chat_id, message_id=mid)
    except Exception:  # noqa: BLE001
        pass


def ask_version(chat_id: int, kind: str, title: str):
    """پرسیدن نسخه تصویری یا متنی با دو دکمه اینلاین."""
    kb = {"inline_keyboard": [[
        {"text": "🖼️ نسخه تصویری", "callback_data": f"v:img:{kind}"},
        {"text": "📝 نسخه متنی", "callback_data": f"v:txt:{kind}"},
    ]]}
    send_message(chat_id, f"{title}\nکدوم نسخه رو می‌خوای؟", reply_markup=kb)


def cmd_today_text(chat_id: int):
    u = get_user(chat_id)
    if not u:
        send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        return
    with ProgressBar(chat_id, "📝 دارم نسخه متنی رو آماده می‌کنم"):
        try:
            text = google_weather_text(u["name"], mode="today")
        except Exception:  # noqa: BLE001
            log.exception("today text failed")
            text = None
    if text:
        send_message(chat_id, text)
    else:
        send_message(chat_id, "😞 نتونستم نسخه متنی رو بگیرم. چند دقیقه دیگه دوباره تلاش کن.")


def cmd_week_text(chat_id: int):
    u = get_user(chat_id)
    if not u:
        send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        return
    with ProgressBar(chat_id, "📝 دارم نسخه متنی رو آماده می‌کنم"):
        try:
            text = google_weather_text(u["name"], mode="week")
        except Exception:  # noqa: BLE001
            log.exception("week text failed")
            text = None
    if text:
        send_message(chat_id, text)
    else:
        send_message(chat_id, "😞 نتونستم نسخه متنی رو بگیرم. چند دقیقه دیگه دوباره تلاش کن.")


def handle_callback(cb: dict):
    qid = cb.get("id")
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    mid = msg.get("message_id")
    data = cb.get("data", "")
    if qid:
        try:
            api("answerCallbackQuery", callback_query_id=qid)
        except Exception:  # noqa: BLE001
            pass
    if not chat_id:
        return
    if mid:
        try:
            api("editMessageReplyMarkup", chat_id=chat_id, message_id=mid,
                reply_markup=json.dumps({"inline_keyboard": []}))
        except Exception:  # noqa: BLE001
            pass
    if data == "v:img:today":
        cmd_today(chat_id)
    elif data == "v:txt:today":
        cmd_today_text(chat_id)
    elif data == "v:img:tomorrow":
        cmd_tomorrow(chat_id)
    elif data == "v:txt:tomorrow":
        cmd_tomorrow_text(chat_id)
    elif data == "v:img:week":
        cmd_week(chat_id)
    elif data == "v:txt:week":
        cmd_week_text(chat_id)


def cmd_today(chat_id: int):
    u = get_user(chat_id)
    if not u:
        send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        return
    if u["name"] == "موقعیت تو":
        data = get_forecast(u["lat"], u["lon"], days=2)
        if not data or "daily" not in data:
            send_message(chat_id, "😞 الان نتونستم هواشناسی رو بگیرم. چند دقیقه دیگه دوباره تلاش کن.")
            return
        send_city_card(chat_id, u["name"], data)
        return
    with ProgressBar(chat_id, "📸 دارم اسکرین‌شات هواشناسی امروز رو می‌گیرم"):
        ok = send_google_shot(chat_id, u["name"], f"🌤️ هواشناسی امروز {u['name']}", mode="today")
    if not ok:
        send_message(chat_id, "😞 نتونستم اسکرین‌شات گوگل رو بگیرم. چند دقیقه دیگه دوباره تلاش کن.")


def cmd_tomorrow(chat_id: int):
    u = get_user(chat_id)
    if not u:
        send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        return
    if u["name"] == "موقعیت تو":
        data = get_forecast(u["lat"], u["lon"], days=2)
        if not data or "daily" not in data:
            send_message(chat_id, "😞 الان نتونستم هواشناسی رو بگیرم.")
            return
        send_city_card(chat_id, u["name"], data)
        return
    with ProgressBar(chat_id, "📸 دارم اسکرین‌شات هواشناسی فردا رو می‌گیرم"):
        ok = send_google_shot(chat_id, u["name"], f"🌧️ هواشناسی فردای {u['name']}", mode="tomorrow")
    if not ok:
        send_message(chat_id, "😞 نتونستم اسکرین‌شات گوگل رو بگیرم. چند دقیقه دیگه دوباره تلاش کن.")


def cmd_tomorrow_text(chat_id: int):
    u = get_user(chat_id)
    if not u:
        send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        return
    with ProgressBar(chat_id, "📝 دارم نسخه متنی رو آماده می‌کنم"):
        try:
            text = google_weather_text(u["name"], mode="tomorrow")
        except Exception:  # noqa: BLE001
            log.exception("tomorrow text failed")
            text = None
    if text:
        send_message(chat_id, text)
    else:
        send_message(chat_id, "😞 نتونستم نسخه متنی رو بگیرم. چند دقیقه دیگه دوباره تلاش کن.")


def cmd_week(chat_id: int):
    u = get_user(chat_id)
    if not u:
        send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        return
    if u["name"] == "موقعیت تو":
        data = get_forecast(u["lat"], u["lon"], days=7)
        if not data or "daily" not in data:
            send_message(chat_id, "😞 الان نتونستم هواشناسی رو بگیرم.")
            return
        send_message(chat_id, forecast_text(u["name"], data, days=7))
        return
    with ProgressBar(chat_id, "📸 دارم اسکرین‌شات پیش‌بینی هفته رو می‌گیرم"):
        ok = send_google_shot(chat_id, u["name"], f"📊 پیش‌بینی ۷ روزه {u['name']}", mode="week")
    if not ok:
        send_message(chat_id, "😞 نتونستم اسکرین‌شات گوگل رو بگیرم. چند دقیقه دیگه دوباره تلاش کن.")


def send_photo_with_retry(chat_id: int, photo_path: str, caption: str = "",
                          attempts: int = 4) -> dict:
    """ارسال عکس با تلاش مجدد (بک‌آف نمایی)؛ اگر همه تلاش‌ها شکست خورد استثنا می‌دهد."""
    delay = 3
    last_exc: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            return send_photo(chat_id, photo_path, caption)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            log.warning("sendPhoto attempt %d/%d failed: %s", i, attempts, e)
            if i < attempts:
                time.sleep(delay)
                delay *= 2
    raise last_exc  # type: ignore[misc]


def send_city_card(chat_id: int, name: str, data: dict):
    """کارت تصویری هواشناسی شهر؛ با تلاش مجدد ارسال می‌شود و هرگز با متن جایگزین نمی‌شود."""
    try:
        card_path = make_weather_card(name, data)
        if not os.path.getsize(card_path):
            raise RuntimeError("empty card file")
    except Exception:  # noqa: BLE001
        log.exception("card render failed")
        send_message(chat_id, "😞 موقع ساخت کارت هواشناسی مشکلی پیش اومد. لطفاً دوباره اسم شهر رو بفرست.")
        return
    try:
        send_photo_with_retry(chat_id, card_path)
    except Exception:  # noqa: BLE001
        log.exception("card send failed after retries")
        send_message(chat_id, "😞 نتونستم کارت هواشناسی رو بفرستم. لطفاً دوباره اسم شهر رو بفرست.")
    finally:
        try:
            os.remove(card_path)
        except OSError:
            pass


def send_google_shot(chat_id: int, city_name: str, caption: str,
                      mode: str = "full", attempts: int = 2) -> bool:
    """اسکرین‌شات هواشناسی گوگل را می‌فرستد. در صورت شکست همه تلاش‌ها False.

    mode: "today" = فقط امروز | "week" = فقط نوار ۸ روزه | "full" = کل ویجت
    """
    with loading(chat_id):
        for i in range(1, attempts + 1):
            path = f"/tmp/gshot_{chat_id}_{i}.png"
            try:
                google_weather_shot(city_name, path, mode=mode)
                try:
                    send_photo_with_retry(chat_id, path, caption)
                finally:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                return True
            except GoogleShotError as e:
                log.warning("google shot attempt %d/%d failed: %s", i, attempts, e)
            except Exception:  # noqa: BLE001
                log.exception("google shot attempt %d/%d failed", i, attempts)
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
    return False


def handle_city_name(chat_id: int, query: str):
    query = query.strip()
    if not query:
        return
    interim = send_message(chat_id, "🔎 دارم شهر رو پیدا می‌کنم...")
    mid = interim["message_id"]
    geo = geocode(query)
    if not geo:
        edit_message(chat_id, mid, f"😕 شهری به اسم «{query}» پیدا نکردم.\nدوباره با املای دیگه امتحان کن، مثلاً: Tehran")
        return
    name, lat, lon = geo
    set_user_city(chat_id, name, lat, lon)
    _drop_interim(chat_id, mid)
    caption = f"✅ {name} ثبت شد! از فردا هر روز صبح ساعت ۷ هواشناسی رو می‌فرستم ☁️"
    with ProgressBar(chat_id, "📸 دارم اسکرین‌شات هواشناسی رو می‌گیرم"):
        ok = send_google_shot(chat_id, name, caption, mode="today")
    if not ok:
        send_message(chat_id, "😞 نتونستم اسکرین‌شات گوگل رو بگیرم. لطفاً دوباره اسم شهر رو بفرست.")


def handle_location(chat_id: int, lat: float, lon: float):
    set_user_city(chat_id, "موقعیت تو", lat, lon)
    data = get_forecast(lat, lon, days=2)
    if not data or "daily" not in data:
        send_message(chat_id, "✅ لوکیشنت ثبت شد!\n\nولی الان نتونستم هواشناسی رو بگیرم 😞")
        return
    send_message(
        chat_id,
        "✅ لوکیشنت ثبت شد! از فردا هر روز صبح ساعت ۷ هواشناسی رو می‌فرستم ☁️",
    )
    send_city_card(chat_id, "موقعیت تو", data)


def _from_info(src: dict) -> tuple[str | None, str | None]:
    fr = src.get("from") or {}
    return fr.get("username"), fr.get("first_name")


def handle_update(u: dict):
    if "callback_query" in u:
        cb = u["callback_query"]
        _cid = ((cb.get("message") or {}).get("chat") or {}).get("id")
        if _cid:
            _un, _fn = _from_info(cb)
            touch_user(_cid, _un, _fn)
        handle_callback(cb)
        return
    msg = u.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return
    _un, _fn = _from_info(msg)
    touch_user(chat_id, _un, _fn)
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return
    if "location" in msg:
        loc = msg["location"]
        handle_location(chat_id, loc["latitude"], loc["longitude"])
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if text.startswith("/start"):
        send_message(chat_id, WELCOME, reply_markup=KEYBOARD)
    elif text.startswith("/help"):
        send_message(chat_id, WELCOME, reply_markup=KEYBOARD)
    elif text == BTN_TODAY or text.startswith("/today"):
        u = get_user(chat_id)
        if not u:
            send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        else:
            ask_version(chat_id, "today", "🌤️ هواشناسی امروز")
    elif text == BTN_TOMORROW or text.startswith("/tomorrow"):
        u = get_user(chat_id)
        if not u:
            send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        else:
            ask_version(chat_id, "tomorrow", "🌧️ هواشناسی فردا")
    elif text == BTN_WEEK or text.startswith("/week"):
        u = get_user(chat_id)
        if not u:
            send_message(chat_id, "اول شهرت رو بفرست 🌍\nمثلاً: تهران")
        else:
            ask_version(chat_id, "week", "📊 پیش‌بینی ۷ روزه")
    elif text == BTN_CITY or text.startswith("/city"):
        send_message(chat_id, "اسم شهر جدید رو بفرست 🌍\nمثلاً: مشهد")
    elif text.startswith("/"):
        send_message(chat_id, "این دستور رو نمی‌شناسم 🤔\n/help رو بزن تا راهنماییت کنم.")
    else:
        handle_city_name(chat_id, text)


def main():
    log.info("bot polling started (short-polling)")
    offset = load_offset()
    while True:
        try:
            # Short-polling به‌جای long-polling: نگه‌داشتن اتصال باز (timeout=25)
            # از پشت پروکسی خروجی هنگ می‌کند و read-timeout می‌دهد؛ با timeout=0
            # هر درخواست فوراً برمی‌گردد و اتصال آویزان نمی‌ماند.
            updates = api("getUpdates", offset=offset, timeout=0)
        except Exception as e:  # noqa: BLE001
            log.warning("poll error: %s", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                handle_update(u)
            except Exception:  # noqa: BLE001
                log.exception("handler failed for update %s", u.get("update_id"))
        if updates:
            save_offset(offset)
        else:
            time.sleep(2)


if __name__ == "__main__":
    # Health-check HTTP server برای رندر (در thread جدا).
    # رندر به پورت $PORT نیاز دارد وگرنه سرویس را down می‌داند.
    def _health_server():
        import http.server
        import socketserver

        port = int(os.environ.get("PORT", "10000"))

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass

        with socketserver.TCPServer(("0.0.0.0", port), Handler) as httpd:
            log.info("health server on port %d", port)
            httpd.serve_forever()

    threading.Thread(target=_health_server, daemon=True).start()
    main()
