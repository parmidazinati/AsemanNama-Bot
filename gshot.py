#!/usr/bin/env python3
"""اسکرین‌شات از ویجت هواشناسی گوگل برای یک شهر.

از یک مرورگر Chromium دائمی (persistent context) استفاده می‌کند تا هر اسکرین‌شات
نیازی به بالا آمدن مجدد مرورگر نداشته باشد (سریع‌تر و کم‌مصرف‌تر).
"""
import logging
import os
import threading
import urllib.parse as _up

from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont, ImageOps

import proxyfwd

log = logging.getLogger("weather")
# در رندر: از کرومیوم داخلی Playwright استفاده می‌شود (CHROME_PATH خالی باشد).
# به‌صورت محلی: /opt/meta-chromium/chrome
CHROME = os.environ.get("CHROME_PATH", "/opt/meta-chromium/chrome") or None
BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE, "chrome_profile")
PAD = 48  # حاشیه سفید دور اسکرین‌شات (پیکسل)
# در رندر نیازی به پروکسی خروجی نیست؛ با USE_PROXY=0 غیرفعال می‌شود.
USE_PROXY = os.environ.get("USE_PROXY", "1") == "1"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class GoogleShotError(RuntimeError):
    pass


_pw = None
_ctx = None
_ctx_lock = threading.Lock()


def _get_context():
    """کانتکست دائمی مرورگر؛ در صورت مرگ مرورگر دوباره می‌سازد."""
    global _pw, _ctx
    with _ctx_lock:
        if _ctx is not None:
            try:
                if _ctx.browser and _ctx.browser.is_connected():
                    return _ctx
            except Exception:  # noqa: BLE001
                pass
            _ctx = None
        if _pw is None:
            _pw = sync_playwright().start()
        args = [
            "--no-sandbox",
            "--ignore-certificate-errors",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ]
        if USE_PROXY:
            args.insert(1, f"--proxy-server={proxyfwd.ensure()}")
        launch_kwargs = dict(
            user_data_dir=PROFILE_DIR,
            args=args,
            viewport={"width": 1280, "height": 900},
            user_agent=UA,
            locale="fa-IR",
        )
        if CHROME:
            launch_kwargs["executable_path"] = CHROME
        _ctx = _pw.chromium.launch_persistent_context(**launch_kwargs)
        log.info("persistent browser ready")
        return _ctx


def _reset_context():
    global _ctx
    with _ctx_lock:
        try:
            if _ctx:
                _ctx.close()
        except Exception:  # noqa: BLE001
            pass
        _ctx = None


def _ensure_celsius(pg, widget) -> bool:
    """مطمئن می‌شود واحد دما سانتی‌گراد است؛ لینک واحد غیرفعال را کلیک می‌کند."""
    for _ in range(3):
        link_txt = pg.evaluate(
            """() => {
                const a = document.querySelector(
                    '#wob_wc .wob-unit a.wob_t:not([style*="display:none"])');
                return a ? a.textContent.trim() : null;
            }"""
        )
        if link_txt is None:
            return True  # لینکی نیست؛ احتمالاً از قبل سانتی‌گراد است
        if "°F" in link_txt:
            return True  # لینک فارنهایت دیده می‌شود یعنی الان سانتی‌گراد فعال است
        pg.evaluate(
            """() => {
                const a = document.querySelector(
                    '#wob_wc .wob-unit a.wob_t:not([style*="display:none"])');
                if (a) a.click();
            }"""
        )
        pg.wait_for_timeout(1500)
    return False


def _crop_today_shot(pg, widget, out_path: str):
    """بخش روزانه (نوار ۸ روزه) را از پایین اسکرین‌شات حذف می‌کند."""
    try:
        wbox = widget.bounding_box() or {}
        strip = pg.query_selector("#wob_dp")
        sbox = strip.bounding_box() if strip else None
        if not wbox.get("height") or not sbox:
            return
        ratio = (sbox["y"] - wbox["y"]) / wbox["height"]
        ratio = max(0.3, min(0.92, ratio))
        img = Image.open(out_path)
        w, h = img.size
        cut = int(h * ratio) - 28
        if cut > 60:
            img.crop((0, 0, w, cut)).save(out_path)
    except Exception as e:  # noqa: BLE001
        log.warning("today crop failed: %s", e)


def _add_padding(out_path: str, border_x: int = PAD, border_y: int = PAD):
    """حاشیه سفید دور اسکرین‌شات تا حس خفگی ندهد."""
    try:
        img = Image.open(out_path).convert("RGB")
        w, h = img.size
        canvas = Image.new("RGB", (w + 2 * border_x, h + 2 * border_y), "white")
        canvas.paste(img, (border_x, border_y))
        canvas.save(out_path)
    except Exception as e:  # noqa: BLE001
        log.warning("padding failed: %s", e)


FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Vazirmatn-Regular.ttf")


def _label_cell(img, alt: str, font_size: int = 34):
    """افزودن کلمه وضعیت (مثلاً «نیمه آفتابی») زیر تصویر سلول روز."""
    cw0, ch0 = img.size
    try:
        label_font = ImageFont.truetype(FONT_PATH, font_size)
    except Exception:  # noqa: BLE001
        label_font = ImageFont.load_default()
    label_h = font_size + 24
    cell = Image.new("RGB", (cw0, ch0 + label_h), "white")
    cell.paste(img, (0, 0))
    if alt and alt.strip():
        dr = ImageDraw.Draw(cell)
        dr.text((cw0 // 2, ch0 + label_h // 2), alt.strip(), font=label_font,
                fill=(70, 70, 70), anchor="mm", direction="rtl")
    return cell


def _week_poster(pg, out_path: str, cols: int = 4, aspect: float = 1.78):
    """پوستر پیش‌بینی هفته: ستون‌های روزهای گوگل در چیدمان راست‌به‌چپ
    با نسبت ابعاد نزدیک به ویجت کامل گوگل (~16:10) + کلمه وضعیت زیر هر روز."""
    from io import BytesIO

    pg.evaluate("document.body.style.zoom='200%'")
    pg.wait_for_timeout(1500)
    days = pg.query_selector_all("#wob_dp .wob_df")
    if len(days) < 7:
        raise GoogleShotError("week strip not found")
    cells = []
    for d in days[:8]:
        try:
            alt = d.evaluate("(el) => { const i = el.querySelector('img'); return i ? i.alt : ''; }") or ""
        except Exception:  # noqa: BLE001
            alt = ""
        img = Image.open(BytesIO(d.screenshot())).convert("RGB")
        w, h = img.size
        img = img.resize((int(w * 1.5), int(h * 1.5)), Image.LANCZOS)
        cells.append(_label_cell(img, alt))
    cw, ch = cells[0].size
    gap = 14
    rows = (len(cells) + cols - 1) // cols
    gw = cols * cw + (cols - 1) * gap
    gh = rows * ch + (rows - 1) * gap
    # رساندن بوم به نسبت ابعاد هدف
    if gw / gh < aspect:
        bw, bh = int(gh * aspect), gh
    else:
        bw, bh = gw, int(gw / aspect)
    pad = 48
    canvas = Image.new("RGB", (bw + 2 * pad, bh + 2 * pad), "white")
    ox, oy = pad + (bw - gw) // 2, pad + (bh - gh) // 2
    for i, img in enumerate(cells):
        r, c = divmod(i, cols)
        x = ox + (cols - 1 - c) * (cw + gap)  # ستون اول سمت راست
        y = oy + r * (ch + gap)
        canvas.paste(img, (x, y))
    canvas.save(out_path)


def _unit_is_celsius(pg) -> bool:
    """بررسی اینکه واحد فعال واقعاً سانتی‌گراد است (نه فقط لینک)."""
    try:
        info = pg.evaluate("""() => ({
          temp: document.querySelector('#wob_tm')?.innerText || '',
          unit: document.querySelector('#wob_wc .wob-unit')?.innerText || ''
        })""")
        t = (info.get("temp") or "").strip().translate(
            str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        if t.lstrip("-").isdigit() and int(t.lstrip("-")) > 50:
            return False  # عدد فارنهایت است
        u = (info.get("unit") or "").replace(" ", "").replace("\n", "")
        return u.startswith("°C")  # واحد فعلی اول نمایش داده می‌شود
    except Exception:  # noqa: BLE001
        return True


def _load_weather_page(city_name: str, timeout_ms: int = 40000, tomorrow: bool = False):
    """صفحه هواشناسی گوگل را باز می‌کند و (pg, widget) برمی‌گرداند.
    در صورت خطا صفحه را می‌بندد؛ در حالت موفق بستن با caller است."""
    when = "فردا " if tomorrow else ""
    q = _up.quote_plus(f"آب و هوای {when}{city_name}")
    url = f"https://www.google.com/search?q={q}&hl=fa"

    ctx = _get_context()
    pg = ctx.new_page()
    try:
        try:
            pg.goto(url, timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if "closed" in msg or "crashed" in msg:
                _reset_context()
                ctx = _get_context()
                pg = ctx.new_page()
                pg.goto(url, timeout=timeout_ms)
            else:
                raise
        pg.wait_for_timeout(2200)

        body = (pg.content() or "")
        low = body[:3000].lower()
        if ("unusual traffic" in low or "ترافیک غیرعادی" in body
                or "recaptcha" in low or "من ربات نیستم" in body):
            raise GoogleShotError("captcha")

        # دیالوگ رضایت گوگل (اگر بود)
        for sel in ("#L2AGLb", 'button:has-text("Accept all")', 'button:has-text("پذیرفتن همه")'):
            try:
                btn = pg.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    pg.wait_for_timeout(1500)
                    break
            except Exception:  # noqa: BLE001
                pass

        pg.wait_for_selector("#wob_wc", timeout=12000)
        widget = pg.query_selector("#wob_wc")
        # سوییچ به سانتی‌گراد (با پروفایل دائمی معمولاً ذخیره می‌ماند)
        _ensure_celsius(pg, widget)
        if tomorrow and not _unit_is_celsius(pg):
            # کوئری «فردا» گاهی واحد را به‌هم می‌ریزد؛ ریلود با کوکی ذخیره‌شده اصلاحش می‌کند
            pg.reload(timeout=timeout_ms)
            pg.wait_for_timeout(2200)
            pg.wait_for_selector("#wob_wc", timeout=12000)
            widget = pg.query_selector("#wob_wc")
            _ensure_celsius(pg, widget)
        return pg, widget
    except Exception:
        try:
            pg.close()
        except Exception:  # noqa: BLE001
            pass
        raise


def extract_week_items(pg) -> list:
    """داده روزهای هفته از روی همان المنت‌هایی که تصویر ازشان ساخته می‌شود."""
    return pg.evaluate("""() => [...document.querySelectorAll('#wob_dp .wob_df')].map(d => {
      const nameEl = d.querySelector('[aria-label]');
      const img = d.querySelector('img');
      return {name: nameEl ? nameEl.getAttribute('aria-label') : '',
              cond: img ? img.alt : '', text: d.innerText || ''};
    })""")


def extract_today_info(pg) -> dict:
    """داده امروز از روی همان ویجتی که تصویر از آن گرفته می‌شود."""
    return pg.evaluate("""() => {
      const g = s => { const e = document.querySelector(s); return e ? e.innerText.trim() : ''; };
      return {temp: g('#wob_tm'), cond: g('#wob_dc'), precip: g('#wob_pp'),
              humidity: g('#wob_hm'), wind: g('#wob_ws')};
    }""")


def google_weather_text(city_name: str, mode: str = "today") -> str:
    """نسخه متنی استخراج‌شده از همان داده‌های تصویر گوگل."""
    import re

    _fa_digits = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

    def fa(s: str) -> str:
        return s.translate(_fa_digits)

    pg, _widget = _load_weather_page(city_name, tomorrow=(mode == "tomorrow"))
    try:
        if mode == "week":
            items = extract_week_items(pg)
            lines = [f"📊 پیش‌بینی ۷ روزهٔ {city_name}", ""]
            for it in items[:8]:
                temps = re.findall(r"[۰-۹0-9]+°", it.get("text", ""))
                temps = [fa(t) for t in temps[::-1]]  # کمینه تا بیشینه
                t = f" — {' تا '.join(temps)}" if temps else ""
                lines.append(f"▪️ {it.get('name', '')}: {it.get('cond', '')}{t}")
            return "\n".join(lines)
        info = extract_today_info(pg)
        title = (f"🌧️ هواشناسی فردای {city_name}" if mode == "tomorrow"
                 else f"🌤️ هواشناسی امروز {city_name}")
        lines = [title, "", f"{fa(info.get('temp', ''))}° — {info.get('cond', '')}"]
        parts = []
        if info.get("precip"):
            parts.append(f"بارش: {fa(info['precip'])}")
        if info.get("humidity"):
            parts.append(f"رطوبت: {fa(info['humidity'])}")
        if info.get("wind"):
            parts.append(f"باد: {fa(info['wind'])}")
        if parts:
            lines.append(" | ".join(parts))
        return "\n".join(lines)
    finally:
        try:
            pg.close()
        except Exception:  # noqa: BLE001
            pass


def google_weather_shot(city_name: str, out_path: str, mode: str = "full",
                        timeout_ms: int = 40000) -> str:
    """از نتیجه هواشناسی گوگل برای شهر عکس می‌گیرد و مسیر فایل را برمی‌گرداند.

    mode: "today" = فقط امروز (تا آخر شب) | "week" = فقط نوار ۸ روزه | "full" = کل ویجت
    در صورت کپچا/خطا GoogleShotError می‌دهد تا caller تصمیم بگیرد.
    """
    pg, widget = _load_weather_page(city_name, timeout_ms, tomorrow=(mode == "tomorrow"))
    try:
        # ویجت هواشناسی گوگل
        try:
            if mode == "week":
                # پوستر ۴×۲؛ در صورت شکست، نوار افقی قبلی
                try:
                    _week_poster(pg, out_path)
                except Exception:  # noqa: BLE001
                    log.warning("week poster failed, falling back to strip")
                    try:
                        pg.evaluate("document.body.style.zoom='170%'")
                        pg.wait_for_timeout(1200)
                    except Exception:  # noqa: BLE001
                        pass
                    strip = pg.query_selector("#wob_dp")
                    (strip or widget).screenshot(path=out_path)
                    _add_padding(out_path, PAD, 100)
            elif mode == "tomorrow":
                # با کوئری «فردا» پنل اصلی همان قالب امروز را برای فردا نشان می‌دهد
                widget.screenshot(path=out_path)
                _crop_today_shot(pg, widget, out_path)
                _add_padding(out_path)
            else:
                widget.screenshot(path=out_path)
                if mode == "today":
                    _crop_today_shot(pg, widget, out_path)
                _add_padding(out_path)
        except Exception:  # noqa: BLE001
            log.warning("weather widget not found, full-page screenshot")
            pg.screenshot(path=out_path)
            _add_padding(out_path)
    finally:
        try:
            pg.close()
        except Exception:  # noqa: BLE001
            pass
    if not os.path.getsize(out_path):
        raise GoogleShotError("empty screenshot")
    return out_path
