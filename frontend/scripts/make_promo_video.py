"""Промо-ролик Seruen из фото Wikimedia Commons и скриншотов демо: Ken Burns, титры, кроссфейды.

python make_video.py <repo> <scratch/video> <out_dir>
"""
import json
import subprocess
import sys

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO, WORK, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
W, H, FPS = 1920, 1080, 30
FADE = 0.6  # сек кроссфейда
FONT = "/System/Library/Fonts/Avenir Next.ttc"
BOLD, DEMI, MED, REG = 0, 2, 5, 7
ACCENT = (64, 196, 255)


def font(size, idx=BOLD):
    return ImageFont.truetype(FONT, size, index=idx)


def load(name):
    if name.startswith("shot:"):
        return Image.open(f"{REPO}/frontend/screenshots/{name[5:]}").convert("RGB")
    return Image.open(f"{WORK}/src/{name}.jpg").convert("RGB")


def fit_rect(img, rect=None):
    """Прямоугольник 16:9 внутри изображения (по умолчанию — максимальный по центру)."""
    iw, ih = img.size
    if rect:
        return rect
    if iw / ih > W / H:
        h = ih
        w = h * W / H
    else:
        w = iw
        h = w * H / W
    return ((iw - w) / 2, (ih - h) / 2, w, h)


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def ease(t):
    return t * t * (3 - 2 * t)


CW, CH = 1440, 810  # окно со скриншотом в сценах «приложение»


def _card_bg():
    bg = Image.new("RGB", (W, H), (10, 18, 34))
    glow = Image.new("RGB", (W, H), (20, 60, 110))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse((W * 0.15, -H * 0.4, W * 0.85, H * 0.7), fill=150)
    bg.paste(glow, (0, 0), mask.filter(ImageFilter.GaussianBlur(160)))
    shadow = Image.new("L", (W, H), 0)
    x0, y0 = (W - CW) // 2, 50
    ImageDraw.Draw(shadow).rounded_rectangle((x0 + 10, y0 + 24, x0 + CW + 10, y0 + CH + 24), 28, fill=170)
    bg.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(28)))
    return bg


CARD_BG = None
CARD_MASK = None


def kenburns(img, start, end, n, card=False):
    global CARD_BG, CARD_MASK
    if card and CARD_BG is None:
        CARD_BG = _card_bg()
        CARD_MASK = Image.new("L", (CW, CH), 0)
        ImageDraw.Draw(CARD_MASK).rounded_rectangle((0, 0, CW - 1, CH - 1), 24, fill=255)
    for i in range(n):
        t = ease(i / max(n - 1, 1))
        x, y, w, h = lerp(start, end, t)
        if not card:
            yield img.resize((W, H), Image.BILINEAR, box=(x, y, x + w, y + h))
            continue
        fr = CARD_BG.copy()
        fr.paste(img.resize((CW, CH), Image.LANCZOS, box=(x, y, x + w, y + h)), ((W - CW) // 2, 50), CARD_MASK)
        yield fr


def zoom(img, z0=1.0, z1=1.12, cx=0.5, cy=0.5, rect=None):
    """start/end прямоугольники для плавного наезда к точке (cx, cy) в долях кадра."""
    x, y, w, h = fit_rect(img, rect)

    def r(z):
        ww, hh = w / z, h / z
        return (x + (w - ww) * cx, y + (h - hh) * cy, ww, hh)
    return r(z0), r(z1)


def pan(img):
    """Широкая панорама: высота кадра = высота фото, движение слева направо."""
    iw, ih = img.size
    h = ih
    w = h * W / H
    return (0, 0, w, h), (iw - w, 0, w, h)


def overlay(title=None, sub=None, small=None, where="bottom", tag=None):
    """RGBA-слой с градиентом и текстом."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad = Image.new("L", (1, H))
    for yy in range(H):
        if where == "bottom":
            a = max(0, (yy - H * 0.45) / (H * 0.55))
        elif where == "center":
            a = 0.55
        elif where == "below":
            a = 0
        else:
            a = max(0, 1 - yy / (H * 0.5))
        grad.putpixel((0, yy), int(255 * min(1, a) * 0.85))
    shade = Image.new("RGBA", (W, H), (8, 14, 28, 255))
    shade.putalpha(grad.resize((W, H)))
    ov = Image.alpha_composite(ov, shade)
    d = ImageDraw.Draw(ov)
    x = 110
    if where == "center":
        y = H // 2 - 130
        if title:
            f = font(150, BOLD)
            tw = d.textlength(title, font=f)
            d.text(((W - tw) / 2, y), title, font=f, fill="white")
        if sub:
            f = font(54, MED)
            tw = d.textlength(sub, font=f)
            d.text(((W - tw) / 2, y + 190), sub, font=f, fill=(225, 235, 245))
        if small:
            f = font(32, REG)
            for k, line in enumerate(small.split("\n")):
                tw = d.textlength(line, font=f)
                d.text(((W - tw) / 2, y + 290 + k * 44), line, font=f, fill=(170, 190, 210))
        return ov
    if where == "below":  # подпись под карточкой со скриншотом, фон уже тёмный
        y = 50 + CH + 46
        if tag:
            f = font(28, DEMI)
            tw = d.textlength(tag, font=f)
            d.rounded_rectangle((x0 := (W - CW) // 2, y - 6, x0 + tw + 32, y + 38), radius=22, fill=ACCENT + (255,))
            d.text((x0 + 16, y - 2), tag, font=f, fill=(8, 20, 35))
            tx = x0 + tw + 56
        else:
            tx = (W - CW) // 2
        d.text((tx, y - 14), title, font=font(60, BOLD), fill="white")
        if sub:
            d.text(((W - CW) // 2, y + 70), sub, font=font(38, MED), fill=(200, 215, 232))
        return ov
    y = H - 300 if where == "bottom" else 110
    if tag:
        f = font(30, DEMI)
        tw = d.textlength(tag, font=f)
        d.rounded_rectangle((x, y - 62, x + tw + 36, y - 12), radius=25, fill=ACCENT + (255,))
        d.text((x + 18, y - 57), tag, font=f, fill=(8, 20, 35))
    if title:
        d.text((x, y), title, font=font(78, BOLD), fill="white")
    if sub:
        d.text((x, y + 104), sub, font=font(42, MED), fill=(220, 232, 244))
    if small:
        d.text((x, y + 170), small, font=font(26, REG), fill=(170, 190, 210))
    return ov


def credit_line(key, credits):
    c = credits.get(key)
    return f"Фото: {c['author']} · {c['license']} · Wikimedia Commons" if c else None


def build_scenes(credits, with_text=True):
    S = []

    def add(src, dur, motion, text=None):
        img = load(src)
        start, end = motion(img)
        S.append((img, start, end, int(dur * FPS), text if with_text else None, src))
        if src.startswith("shot:") and text:
            text["where"] = "below"

    add("baiterek_night", 5.0, lambda im: zoom(im, 1.0, 1.15, 0.62, 0.35),
        dict(title="Seruen", sub="ИИ-помощник по прогулкам в Астане", where="center",
             small=credit_line("baiterek_night", credits)))
    add("panorama", 4.5, pan,
        dict(title="Куда пойти прямо сейчас?", sub="Рядом с вами — с учётом времени, погоды и часов работы",
             small=credit_line("panorama", credits)))
    if with_text:
        add("shot:03-night-kz-desktop.png", 4.5,
            lambda im: zoom(im, 1.0, 1.35, 0.0, 0.2),
            dict(tag="ОТ БАЙТЕРЕКА", title="Вечер у Байтерека", sub="Необычное рядом — 600 м, 11 минут пешком"))
        add("shot:00-start-desktop.png", 4.0,
            lambda im: zoom(im, 1.0, 1.35, 0.0, 0.3),
            dict(tag="ЗАПРОС", title="Скажите своими словами", sub="«Тихое место с кофе и розеткой рядом»"))
        add("shot:01-walk-desktop.png", 4.5,
            lambda im: zoom(im, 1.0, 1.35, 0.0, 0.35),
            dict(tag="1–3 МЕСТА", title="Почему, сколько идти, что делать", sub="Плюс мини-маршрут на карте"))
        add("shot:02-winter-desktop.png", 4.0,
            lambda im: zoom(im, 1.0, 1.35, 0.0, 0.45),
            dict(tag="ПОГОДА", title="−20 °C? Подскажем, где в тепле", sub="Честно: часы неизвестны — так и скажем"))
    for key, tag, title in [("coffee", "КОФЕ", "Тихо, с розеткой и Wi-Fi"),
                            ("park", "ПРОГУЛКА", "Парки и бульвары на 30–60 минут"),
                            ("pool", "СПОРТ И ОТДЫХ", "Бассейны, фитнес, сауны"),
                            ("playground", "С РЕБЁНКОМ", "Площадки, интерактивные музеи")]:
        add(key, 2.2, lambda im: zoom(im, 1.05, 1.18, 0.5, 0.5),
            dict(tag=tag, title=title, small=credit_line(key, credits)))
    add("khan_shatyr", 3.6, lambda im: zoom(im, 1.0, 1.12, 0.5, 0.4),
        dict(title="3000+ мест Астаны", sub="OpenStreetMap · Wikidata · 2GIS — сбор автоматизирован",
             small=credit_line("khan_shatyr", credits)))
    add("expo", 3.4, lambda im: zoom(im, 1.12, 1.0, 0.5, 0.5),
        dict(title="Пешком, на такси, вдвоём или с детьми", sub="Русский · Казахский · English",
             small=credit_line("expo", credits)))
    add("winter", 5.0, pan,
        dict(title="Seruen", sub="Куда пойти в Астане — прямо сейчас", where="center",
             small="NIC Smart City Hackathon · 2026\n" + (credit_line("winter", credits) or "")))
    return S


def render(scenes, path, crf=20):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen([ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                             "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", path],
                            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fade_n = int(FADE * FPS)
    tail = []  # последние кадры предыдущей сцены — смешиваются с началом следующей
    total = 0
    last = len(scenes) - 1
    for si, (img, start, end, n, text, _) in enumerate(scenes):
        ov = overlay(**text) if text else None
        new_tail = []
        for i, fr in enumerate(kenburns(img, start, end, n, card=_.startswith("shot:"))):
            if ov is not None:
                a = max(0.0, min(1.0, i / (0.5 * FPS), (n - 1 - i) / (0.4 * FPS)))
                o = ov.copy()
                o.putalpha(o.getchannel("A").point(lambda v, a=a: int(v * a)))
                fr = Image.alpha_composite(fr.convert("RGBA"), o).convert("RGB")
            arr = np.asarray(fr, dtype=np.float32)
            if i < len(tail):
                t = (i + 1) / (len(tail) + 1)
                arr = tail[i] * (1 - t) + arr * t
            if si < last and i >= n - fade_n:
                new_tail.append(arr)
                continue
            if si == last and i >= n - fade_n:  # затемнение в конце
                arr = arr * ((n - i) / (fade_n + 1))
            proc.stdin.write(arr.astype(np.uint8).tobytes())
            total += 1
        tail = new_tail
    # плавное затемнение в конце уже есть в тексте; закрываем
    proc.stdin.close()
    proc.wait()
    return total / FPS


if __name__ == "__main__":
    credits = {c["key"]: c for c in json.load(open(f"{WORK}/credits.json"))}
    d1 = render(build_scenes(credits, True), f"{OUT}/seruen-promo.mp4", crf=23)
    loop_scenes = [s for s in build_scenes(credits, False) if s[5] in
                   ("baiterek_night", "panorama", "khan_shatyr", "expo", "winter")]
    d2 = render(loop_scenes, f"{OUT}/seruen-hero-loop.mp4", crf=24)
    print(f"promo {d1:.1f}s, loop {d2:.1f}s")
