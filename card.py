#!/usr/bin/env python3
"""ساخت کارت تصویری هواشناسی «آسمان نما» با PIL + فونت وزیرمتن."""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(BASE, "fonts", "Vazirmatn-Bold.ttf")
FONT_REG = os.path.join(BASE, "fonts", "Vazirmatn-Regular.ttf")

W, H = 1080, 1450
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

MONTHS_FA = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

WEEKDAY_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

COND_FA = {
    0: "صاف", 1: "کمی ابری", 2: "نیمه‌ابری", 3: "ابری",
    45: "مه‌آلود", 48: "مه یخ‌زده",
    51: "نم‌نم باران", 53: "نم‌نم باران", 55: "نم‌نم باران",
    56: "باران یخ‌زده", 57: "باران یخ‌زده",
    61: "باران خفیف", 63: "باران", 65: "باران شدید",
    66: "باران یخ‌زده", 67: "باران یخ‌زده شدید",
    71: "برف خفیف", 73: "برف", 75: "برف شدید", 77: "دانه‌های برف",
    80: "رگبار خفیف", 81: "رگبار", 82: "رگبار شدید",
    85: "برف", 86: "برف شدید",
    95: "رعد و برق", 96: "رعد و برق با تگرگ", 99: "رعد و برق با تگرگ شدید",
}


def fa_num(x) -> str:
    return str(x).translate(FA_DIGITS)


def fa(text: str) -> str:
    # شکل‌دهی و جهت متن فارسی را موتور raqm خود PIL انجام می‌دهد
    # (با direction="rtl" در draw.text)؛ پس متن دست‌نخورده می‌ماند.
    return text


def cond_group(code: int) -> str:
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly"
    if code in (3, 45, 48):
        return "cloudy"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "rain"


# (top_rgb, bottom_rgb, dark_text?)
THEMES = {
    "clear": ((18, 100, 190), (80, 170, 245), False),
    "partly": ((30, 110, 180), (125, 185, 225), False),
    "cloudy": ((65, 85, 108), (140, 160, 185), False),
    "rain": ((32, 52, 78), (92, 122, 158), False),
    "snow": ((150, 190, 222), (228, 242, 252), True),
    "storm": ((18, 26, 52), (72, 86, 132), False),
}


def gradient_bg(theme):
    top, bottom, _ = THEMES[theme]
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(
            int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))
    # دایره‌های تزئینی محو
    for cx, cy, r, alpha in ((180, 250, 260, 26), (920, 1050, 320, 22), (850, 180, 150, 30)):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse(
            [cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, alpha))
        img = Image.alpha_composite(img, layer)
    return img


def draw_sun(d, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 213, 79), outline=(255, 179, 0), width=8)
    for i in range(8):
        import math
        a = math.pi / 4 * i + math.pi / 8
        x1, y1 = cx + math.cos(a) * (r + 28), cy + math.sin(a) * (r + 28)
        x2, y2 = cx + math.cos(a) * (r + 95), cy + math.sin(a) * (r + 95)
        d.line([(x1, y1), (x2, y2)], fill=(255, 202, 40), width=14, joint="curve")


def draw_cloud(d, cx, cy, w, color=(255, 255, 255)):
    """ابر فلت کلاسیک: میله پایینی گرد + برجستگی‌های بالا."""
    u = w / 100
    d.rectangle([cx - 42 * u, cy - 8 * u, cx + 42 * u, cy + 18 * u], fill=color)
    d.ellipse([cx - 52 * u, cy - 8 * u, cx - 32 * u, cy + 18 * u], fill=color)
    d.ellipse([cx + 32 * u, cy - 8 * u, cx + 52 * u, cy + 18 * u], fill=color)
    d.ellipse([cx - 40 * u, cy - 32 * u, cx - 4 * u, cy + 4 * u], fill=color)
    d.ellipse([cx - 18 * u, cy - 46 * u, cx + 22 * u, cy - 6 * u], fill=color)
    d.ellipse([cx + 10 * u, cy - 34 * u, cx + 42 * u, cy - 2 * u], fill=color)


def draw_condition(d, cx, cy, s, code):
    """آیکون وضعیت هوا در مرکز (cx, cy) با مقیاس s."""
    g = cond_group(code)
    if g == "clear":
        draw_sun(d, cx, cy, int(s * 0.62))
    elif g == "partly":
        draw_sun(d, cx + s * 0.42, cy - s * 0.35, int(s * 0.4))
        draw_cloud(d, cx - s * 0.08, cy + s * 0.18, int(s * 1.05))
    elif g == "cloudy":
        draw_cloud(d, cx + s * 0.15, cy - s * 0.15, int(s * 0.85), (215, 228, 240))
        draw_cloud(d, cx - s * 0.1, cy + s * 0.2, int(s * 1.1))
    elif g == "rain":
        draw_cloud(d, cx, cy - s * 0.18, int(s * 1.0), (232, 240, 248))
        for i, dx in enumerate((-s * 0.32, 0, s * 0.32)):
            x = cx + dx
            d.line([(x + 14, cy + s * 0.28), (x - 14, cy + s * 0.62)],
                   fill=(140, 200, 255), width=13, joint="curve")
    elif g == "snow":
        draw_cloud(d, cx, cy - s * 0.18, int(s * 1.0), (255, 255, 255))
        for dx, dy in ((-s * 0.3, s * 0.38), (0, s * 0.52), (s * 0.3, s * 0.38)):
            x, y, r = cx + dx, cy + dy, 13
            d.ellipse([x - r, y - r, x + r, y + r], fill=(110, 160, 210))
    elif g == "storm":
        draw_cloud(d, cx, cy - s * 0.22, int(s * 1.0), (88, 104, 124))
        x, y = cx + s * 0.05, cy + s * 0.05
        d.polygon([(x + 30, y), (x - 45, y + 110), (x - 5, y + 110),
                   (x - 30, y + 210), (x + 55, y + 90), (x + 12, y + 90)],
                  fill=(255, 213, 79))
    else:  # fog
        draw_cloud(d, cx, cy - s * 0.2, int(s * 1.0), (232, 240, 248))
        for i, dy in enumerate((s * 0.32, s * 0.48, s * 0.64)):
            wline = s * (0.75 - i * 0.12)
            d.line([(cx - wline / 2, cy + dy), (cx + wline / 2, cy + dy)],
                   fill=(200, 215, 230), width=11)


def _temp_color(t: float):
    """رنگ دما: آبی (سرد) تا نارنجی (گرم)."""
    k = max(0.0, min(1.0, (t - 0) / 35.0))
    cold, hot = (110, 180, 255), (255, 150, 60)
    return tuple(int(cold[i] + (hot[i] - cold[i]) * k) for i in range(3))


def make_week_card(city: str, data: dict) -> str:
    """کارت بزرگ پیش‌بینی ۷ روزه. مسیر PNG را برمی‌گرداند."""
    import datetime as _dt

    daily = data["daily"]
    n = min(7, len(daily["time"]))
    theme = cond_group(int(daily["weathercode"][0]))
    _, _, dark = THEMES[theme]
    ink = (28, 48, 72) if dark else (255, 255, 255)
    sub = (60, 80, 105) if dark else (222, 235, 248)

    ROW_H, HEADER, FOOTER = 160, 340, 70
    H2 = HEADER + n * ROW_H + FOOTER
    # گرادیان پس‌زمینه برای ارتفاع کارت
    img = Image.new("RGBA", (W, H2))
    d = ImageDraw.Draw(img)
    top, bottom, _ = THEMES[theme]
    for y in range(H2):
        t = y / (H2 - 1)
        d.line([(0, y), (W, y)],
               fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,))

    f_brand = ImageFont.truetype(FONT_REG, 38)
    f_city = ImageFont.truetype(FONT_BOLD, 80)
    f_sub = ImageFont.truetype(FONT_REG, 44)
    f_day = ImageFont.truetype(FONT_BOLD, 46)
    f_date = ImageFont.truetype(FONT_REG, 32)
    f_cond = ImageFont.truetype(FONT_REG, 40)
    f_tmax = ImageFont.truetype(FONT_BOLD, 56)
    f_tmin = ImageFont.truetype(FONT_REG, 38)
    f_pop = ImageFont.truetype(FONT_REG, 30)
    f_foot = ImageFont.truetype(FONT_REG, 34)

    cx = W // 2
    d.text((cx, 52), fa("آسمان نما"), font=f_brand, fill=sub, anchor="ma", direction="rtl")
    d.text((cx, 142), fa(city), font=f_city, fill=ink, anchor="ma", direction="rtl")
    d.text((cx, 278), fa("پیش‌بینی ۷ روزه"), font=f_sub, fill=sub, anchor="ma", direction="rtl")
    d.line([(120, HEADER - 18), (W - 120, HEADER - 18)], fill=sub + (110,), width=2)

    tmaxs = [daily["temperature_2m_max"][i] for i in range(n)]
    tmins = [daily["temperature_2m_min"][i] for i in range(n)]
    wmin, wmax = min(tmins), max(tmaxs)
    span = max(1.0, wmax - wmin)

    for i in range(n):
        y0 = HEADER + i * ROW_H
        yc = y0 + ROW_H // 2
        wd = WEEKDAY_FA[_dt.date.fromisoformat(daily["time"][i]).weekday()]
        code = int(daily["weathercode"][i])
        tmax, tmin = round(tmaxs[i]), round(tmins[i])
        pop = daily["precipitation_probability_max"][i]

        # روز و تاریخ (راست)
        d.text((905, y0 + 42), fa(wd), font=f_day, fill=ink, anchor="ma", direction="rtl")
        d.text((905, y0 + 100), fa(jalali(daily["time"][i])), font=f_date,
               fill=sub, anchor="ma", direction="rtl")
        # آیکون
        draw_condition(d, 705, yc, 58, code)
        # وضعیت
        d.text((520, yc), fa(COND_FA.get(code, "")), font=f_cond,
               fill=ink, anchor="ma", direction="rtl")
        # دما
        d.text((300, y0 + 48), fa(f"{fa_num(tmax)}°"), font=f_tmax,
               fill=ink, anchor="ma", direction="rtl")
        d.text((300, y0 + 108), fa(f"{fa_num(tmin)}°"), font=f_tmin,
               fill=sub, anchor="ma", direction="rtl")
        # نوار بازه دما
        bx0, bx1, by = 90, 210, y0 + ROW_H - 26
        d.rounded_rectangle([bx0, by - 7, bx1, by + 7], radius=7, fill=sub + (70,))
        px0 = bx0 + (tmin - wmin) / span * (bx1 - bx0)
        px1 = bx0 + (tmax - wmin) / span * (bx1 - bx0)
        d.rounded_rectangle([px0, by - 7, px1, by + 7], radius=7,
                            fill=_temp_color((tmax + tmin) / 2) + (255,))
        # احتمال بارش
        if pop:
            d.text((150, by - 46), fa(f"{fa_num(pop)}٪"), font=f_pop,
                   fill=(140, 200, 255) if not dark else (40, 110, 180),
                   anchor="ma", direction="rtl")

        if i < n - 1:
            d.line([(90, y0 + ROW_H), (W - 90, y0 + ROW_H)], fill=sub + (45,), width=1)

    d.text((cx, H2 - 38), "@AsemanNamaBot", font=f_foot, fill=sub,
           anchor="ma", direction="ltr")

    out = f"/tmp/asemannama_week_{os.getpid()}.png"
    img.convert("RGB").save(out, "PNG")
    return out


def jalali(iso_date: str) -> str:
    import jdatetime
    d = jdatetime.date.fromgregorian(
        year=int(iso_date[0:4]), month=int(iso_date[5:7]), day=int(iso_date[8:10]))
    return f"{fa_num(d.day)} {MONTHS_FA[d.month - 1]}"


def make_weather_card(city: str, data: dict) -> str:
    """data: خروجی get_forecast با current و daily (حداقل ۲ روز). مسیر PNG را برمی‌گرداند."""
    daily = data["daily"]
    cur = data.get("current") or {}

    code_today = int(daily["weathercode"][0])
    theme = cond_group(code_today)
    _, _, dark = THEMES[theme]
    ink = (28, 48, 72) if dark else (255, 255, 255)
    sub = (60, 80, 105) if dark else (225, 238, 250)

    img = gradient_bg(theme)
    d = ImageDraw.Draw(img)

    f_brand = ImageFont.truetype(FONT_REG, 40)
    f_city = ImageFont.truetype(FONT_BOLD, 96)
    f_date = ImageFont.truetype(FONT_REG, 44)
    f_temp = ImageFont.truetype(FONT_BOLD, 175)
    f_cond = ImageFont.truetype(FONT_BOLD, 62)
    f_stats = ImageFont.truetype(FONT_REG, 46)
    f_sec = ImageFont.truetype(FONT_BOLD, 50)
    f_small = ImageFont.truetype(FONT_REG, 44)
    f_foot = ImageFont.truetype(FONT_REG, 36)

    cx = W // 2
    d.text((cx, 70), fa("آسمان نما"), font=f_brand, fill=sub, anchor="ma", direction="rtl")
    d.text((cx, 185), fa(city), font=f_city, fill=ink, anchor="ma", direction="rtl")

    import datetime as _dt
    wd = WEEKDAY_FA[_dt.date.fromisoformat(daily["time"][0]).weekday()]
    d.text((cx, 305), fa(f"{wd} {jalali(daily['time'][0])}"), font=f_date, fill=sub, anchor="ma", direction="rtl")

    draw_condition(d, cx, 600, 220, code_today)

    t_now = round(cur.get("temperature_2m", daily["temperature_2m_max"][0]))
    d.text((cx, 880), fa(f"{fa_num(t_now)}°"), font=f_temp, fill=ink, anchor="ma", direction="rtl")
    d.text((cx, 1095), fa(COND_FA.get(code_today, "")), font=f_cond, fill=ink, anchor="ma", direction="rtl")

    tmax, tmin = round(daily["temperature_2m_max"][0]), round(daily["temperature_2m_min"][0])
    pop = daily["precipitation_probability_max"][0]
    pop_txt = f"{fa_num(pop)}٪" if pop is not None else "—"
    stats = f"بیشینه {fa_num(tmax)}° | کمینه {fa_num(tmin)}° | بارش {pop_txt}"
    d.text((cx, 1175), fa(stats), font=f_stats, fill=sub, anchor="ma", direction="rtl")

    # جداکننده
    d.line([(140, 1245), (W - 140, 1245)], fill=sub + (110,), width=2)

    if len(daily["time"]) > 1:
        wd2 = WEEKDAY_FA[_dt.date.fromisoformat(daily["time"][1]).weekday()]
        code2 = int(daily["weathercode"][1])
        tmax2, tmin2 = round(daily["temperature_2m_max"][1]), round(daily["temperature_2m_min"][1])
        d.text((cx, 1283), fa(f"فردا — {wd2}"), font=f_sec, fill=ink, anchor="ma", direction="rtl")
        d.text((cx, 1350),
               fa(f"{COND_FA.get(code2, '')} | بیشینه {fa_num(tmax2)}° کمینه {fa_num(tmin2)}°"),
               font=f_small, fill=sub, anchor="ma", direction="rtl")

    d.text((cx, H - 38), "@AsemanNamaBot", font=f_foot, fill=sub, anchor="ma", direction="ltr")

    out = f"/tmp/asemannama_card_{os.getpid()}.png"
    img.convert("RGB").save(out, "PNG")
    return out
