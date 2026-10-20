"""Обзор проекта Seruen для демо-дня: сцены + озвучка (macOS say, голос Milena) + слайды.

python make_overview.py <repo> <scratch/video> <out.mp4>
"""
import json
import os
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REPO, WORK, OUTFILE = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [sys.argv[0], REPO, WORK, os.path.dirname(OUTFILE)]
import make_video as mv  # noqa: E402

W, H, FPS = mv.W, mv.H, mv.FPS
FADE = mv.FADE
NAVY = (10, 18, 34)
ACC = mv.ACCENT
SR = 44100
AUD = f"{WORK}/aud"
os.makedirs(AUD, exist_ok=True)

credits = {c["key"]: c for c in json.load(open(f"{WORK}/credits.json"))}


def cred(k):
    return mv.credit_line(k, credits)


# ---------- слайды ----------

def slide_bg():
    bg = Image.new("RGB", (W, H), NAVY)
    glow = Image.new("RGB", (W, H), (22, 64, 118))
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse((W * 0.45, -H * 0.5, W * 1.3, H * 0.8), fill=140)
    bg.paste(glow, (0, 0), m.filter(ImageFilter.GaussianBlur(200)))
    return bg


def slide(kicker, title, body=None, draw_extra=None):
    im = slide_bg()
    d = ImageDraw.Draw(im)
    x = 130
    f = mv.font(30, mv.DEMI)
    tw = d.textlength(kicker, font=f)
    d.rounded_rectangle((x, 160, x + tw + 36, 210), 25, fill=ACC)
    d.text((x + 18, 164), kicker, font=f, fill=(8, 20, 35))
    d.text((x, 245), title, font=mv.font(88, mv.BOLD), fill="white")
    if body:
        y = 450
        for line in body:
            if line.startswith("•"):
                d.ellipse((x + 4, y + 26, x + 22, y + 44), fill=ACC)
                d.text((x + 50, y), line[1:].strip(), font=mv.font(52, mv.MED), fill=(225, 235, 245))
                y += 112
            else:
                d.text((x, y), line, font=mv.font(40, mv.REG), fill=(190, 205, 222))
                y += 70
    if draw_extra:
        draw_extra(im, d)
    return im


def stat_tiles(items, y=470):
    def draw(im, d):
        n = len(items)
        gap = 36
        tw = (W - 260 - gap * (n - 1)) / n
        for i, (big, small) in enumerate(items):
            x0 = 130 + i * (tw + gap)
            d.rounded_rectangle((x0, y, x0 + tw, y + 360), 28, fill=(18, 34, 60), outline=(40, 80, 130), width=2)
            d.text((x0 + 40, y + 44), big, font=mv.font(104, mv.BOLD), fill=ACC)
            yy = y + 210
            for line in small.split("\n"):
                d.text((x0 + 40, yy), line, font=mv.font(40, mv.MED), fill=(215, 228, 242))
                yy += 54
    return draw


def flow(steps, y=450):
    def draw(im, d):
        n = len(steps)
        gap = 46
        bw = (W - 260 - gap * (n - 1)) / n
        for i, (head, sub, who) in enumerate(steps):
            x0 = 130 + i * (bw + gap)
            col = (24, 52, 92) if who == "код" else (36, 70, 46)
            d.rounded_rectangle((x0, y, x0 + bw, y + 380), 24, fill=col)
            d.text((x0 + 26, y + 26), who.upper(), font=mv.font(26, mv.DEMI), fill=ACC if who == "код" else (150, 230, 160))
            yy = y + 72
            for line in head.split(" ", 1):
                d.text((x0 + 26, yy), line, font=mv.font(40, mv.BOLD), fill="white")
                yy += 50
            yy += 22
            for line in sub.split("\n"):
                d.text((x0 + 26, yy), line, font=mv.font(30, mv.REG), fill=(205, 220, 236))
                yy += 42
            if i < n - 1:
                ax = x0 + bw + 9
                d.polygon([(ax, y + 175), (ax + 28, y + 190), (ax, y + 205)], fill=(150, 175, 205))
        d.text((130, y + 430), "Gemini видит только 8–10 кандидатов с фактами; расстояние, время и часы считает код.",
               font=mv.font(34, mv.MED), fill=(200, 215, 232))
    return draw


# ---------- сцены: (визуал, озвучка) ----------

def photo(key, motion, text):
    img = mv.load(key)
    s, e = motion(img)
    return ("photo", img, s, e, text)


def shot(name, motion, text):
    img = mv.load("shot:" + name)
    s, e = motion(img)
    text = dict(text, where="below")
    return ("shot", img, s, e, text)


RAW = f"{REPO}/frontend/public/video/raw-site-demo.mp4"


def clip(a, b, text):
    return ("clip", (a, b), None, None, dict(text, where="below"))


def clip_frames(a, b, n):
    """Кадры фрагмента [a, b) сырой записи, растянутые/ускоренные ровно в n кадров, в карточке."""
    ff = mv.imageio_ffmpeg.get_ffmpeg_exe()
    speed = (b - a) / (n / FPS)
    cmd = [ff, "-loglevel", "error", "-ss", str(a), "-t", str(b - a), "-i", RAW,
           "-vf", f"setpts=PTS/{speed:.4f},fps={FPS},scale={mv.CW}:{mv.CH}:flags=lanczos",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    sz = mv.CW * mv.CH * 3
    frames = [Image.frombytes("RGB", (mv.CW, mv.CH), raw[i:i + sz]) for i in range(0, len(raw) - sz + 1, sz)]
    if mv.CARD_BG is None:
        list(mv.kenburns(Image.new("RGB", (W, H)), (0, 0, W, H), (0, 0, W, H), 1, card=True))
    for i in range(n):
        fr = mv.CARD_BG.copy()
        fr.paste(frames[min(i, len(frames) - 1)], ((W - mv.CW) // 2, 50), mv.CARD_MASK)
        yield fr


def still(im):
    s, e = mv.zoom(im, 1.0, 1.04, 0.5, 0.5)
    return ("still", im, s, e, None)


SCENES = [
    (photo("baiterek_night", lambda im: mv.zoom(im, 1.0, 1.15, 0.62, 0.35),
           dict(title="Seruen", sub="ИИ-помощник по прогулкам в Астане", where="center",
                small="Build with AI · задача НИЦ Smart City\n" + cred("baiterek_night"))),
     "Seruen — ИИ-помощник по прогулкам в Астане. За несколько секунд он отвечает на вопрос: куда сходить прямо сейчас?"),
    (still(slide("ПРОБЛЕМА", "Карты, чат-боты и −25 °C", [
        "• Карты: сотни точек, но не ответ «что мне сделать за час»",
        "• Чат-боты выдумывают места и не знают, открыто ли сейчас",
        "• Зимой −25 °C и ветер — «прогуляйтесь по набережной» вредно",
        "• Туристам некогда разбираться в отзывах и часах работы"])),
     "Карты показывают сотни точек, но не говорят, что сделать за свободный час. Чат-боты отвечают гладко, но выдумывают места и не знают, открыто ли сейчас. А в Астане зимой минус двадцать пять и ветер: совет прогуляться по набережной может навредить."),
    (photo("panorama", mv.pan, dict(title="Решение: чат + карта",
                                    sub="Своими словами, на русском, казахском или английском", small=cred("panorama"))),
     "Seruen — это чат и карта. Вы пишете запрос своими словами, на русском, казахском или английском, и получаете от одного до трёх реальных мест рядом: почему именно они, сколько идти, что там делать и насколько мы уверены, что место открыто."),
    (clip(0.0, 37.0, dict(tag="ДЕМО · ОТ БАЙТЕРЕКА", title="Запрос своими словами",
                          sub="«Хочу тихое место с кофе и розеткой» — 3 места, маршрут, «что учтено»")),
     "Откроем Seruen у Байтерека и напишем своими словами: хочу тихое место с кофе и розеткой. Через несколько секунд — три места рядом. У каждого — почему именно оно, сколько идти, часы работы, фото и источник. Ниже — мини-маршрут и блок «что учтено»: локация, время, погода и фильтры."),
    (clip(38.0, 65.0, dict(tag="ДЕМО", title="Необычное ночью", sub="Только то, что открыто сейчас — с маршрутом")),
     "Пресет «Необычное ночью»: только то, что открыто прямо сейчас — квесты и развлечения рядом, с маршрутом по ночному городу."),
    (clip(66.0, 100.0, dict(tag="ДЕМО · ПОГОДА", title="Вечер, −20 °C", sub="Ведём в тепло: кино и кафе в шаговой доступности")),
     "Вечер, минус двадцать. Seruen ведёт в тепло — кинотеатр и кафе в шаговой доступности, без долгих переходов по морозу."),
    (clip(101.0, 129.0, dict(tag="ДЕМО", title="С ребёнком", sub="Детские центры и площадки — и что там делать ребёнку")),
     "С ребёнком днём: детские центры и площадки рядом, и подсказка, чем там заняться именно ребёнку."),
    (clip(130.0, 157.0, dict(tag="ДЕМО · KZ", title="Три языка", sub="Русский, казахский, английский")),
     "И всё то же самое — на казахском и английском языках."),
    (still(slide("КАК ЭТО РАБОТАЕТ", "RAG: ИИ не придумывает места", None, flow([
        ("Разбор запроса", "время, компания,\nограничения", "Gemini"),
        ("Жёсткие фильтры", "радиус, часы работы,\nдети, погода", "код"),
        ("Гибридный поиск", "эмбеддинги Gemini\n+ BM25", "код"),
        ("Генерация", "выбор 1–3 мест,\n«почему» и план", "Gemini"),
        ("Валидатор", "проверка id, цифр\nи «открыто»", "код")]))),
     "Главный принцип: модель не придумывает места и не считает цифры. Код фильтрует кандидатов по расстоянию, часам работы и погоде. Гибридный поиск — эмбеддинги Gemini плюс BM25 — находит подходящие места. Gemini выбирает и объясняет, а валидатор проверяет каждый ответ."),
    (still(slide("ДАННЫЕ", "База собирается автоматически", None, stat_tiles([
        ("3039", "мест Астаны\nв полной базе"), ("53 %", "с часами\nработы"),
        ("3", "источника: OSM,\nWikidata, 2GIS"), ("1", "команда:\nrun_all.py")])) ),
     "Базу собирает одна команда, автоматически: OpenStreetMap, Wikidata и 2GIS — больше трёх тысяч мест Астаны с часами работы, тегами, фото и лицензиями. Открытая часть данных публикуется вместе с кодом."),
    (still(slide("КАЧЕСТВО", "38 тестовых сценариев", None, stat_tiles([
        ("0", "выдуманных\nмест"), ("0", "рекомендаций\nзакрытого"), ("100 %", "релевантность\n(42 из 42)"),
        ("3,5 с", "медианное\nвремя ответа")])) ),
     "На тридцати восьми тестовых сценариях: ноль выдуманных мест, ноль рекомендаций закрытого, сто процентов релевантности, а медианное время ответа — около трёх с половиной секунд."),
    (still(slide("ЭТИКА И ПРИВАТНОСТЬ", "Приватность по умолчанию", [
        "• Координаты огрубляются до ~100 м прямо в браузере",
        "• Без аккаунтов и истории запросов, координаты не храним",
        "• Факт из базы и «идея ИИ» всегда разделены",
        "• Ночью — только открытые и людные места; номер 112"])),
     "Приватность по умолчанию: координаты огрубляются до ста метров прямо в браузере, нет аккаунтов и истории запросов. Факт из базы и идея ИИ всегда разделены, а ночью мы советуем только открытые и людные места."),
    (photo("khan_shatyr", lambda im: mv.zoom(im, 1.0, 1.12, 0.5, 0.4),
           dict(title="Ценность для города", sub="Жителям и туристам — в любую погоду; акимату — аналитика спроса",
                small=cred("khan_shatyr"))),
     "Для города это помощник для жителей и туристов в любую погоду и обезличенная аналитика спроса для акимата и НИЦ Smart City. Для отелей, аэропорта и торговых центров — виджет «куда сходить рядом»."),
    (still(slide("ПЛАН РАЗВИТИЯ", "Что дальше", [
        "• 0–3 мес.: события города, отзывы, «место закрыто» в один клик",
        "• 3–6 мес.: дашборд спроса для НИЦ Smart City, голос на казахском",
        "• 6–12 мес.: Visit Astana, аэропорт, отели, городские сервисы",
        "• Алматы и Шымкент — тот же автоматический конвейер"])),
     "Дальше — события города и отзывы, дашборд спроса для НИЦ Smart City, голосовой ввод на казахском, интеграции с Visit Astana, аэропортом и отелями. А затем — Алматы и Шымкент: конвейер данных тот же."),
    (photo("winter", mv.pan, dict(title="Seruen", sub="Куда пойти в Астане — прямо сейчас", where="center",
                                  small="Build with AI · НИЦ Smart City · 2026\n" + cred("winter"))),
     "Seruen. Куда пойти в Астане — прямо сейчас."),
]


def render(scenes, path, crf=22):
    ff = mv.imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen([ff, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                             "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", path],
                            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fade_n = int(FADE * FPS)
    tail, total, last = [], 0, len(scenes) - 1
    for si, (kind, img, start, end, n, text) in enumerate(scenes):
        ov = mv.overlay(**text) if text else None
        if kind == "clip":
            frames = clip_frames(img[0], img[1], n)
        else:
            frames = mv.kenburns(img, start, end, n, card=(kind == "shot"))
        new_tail = []
        for i, fr in enumerate(frames):
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
            if si == last and i >= n - fade_n:
                arr = arr * ((n - i) / (fade_n + 1))
            proc.stdin.write(arr.astype(np.uint8).tobytes())
            total += 1
        tail = new_tail
    proc.stdin.close()
    proc.wait()
    return total / FPS


def tts(i, text):
    aiff, wav = f"{AUD}/s{i}.aiff", f"{AUD}/s{i}.wav"
    subprocess.run(["say", "-v", "Milena", "-r", "178", "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", "-c", "1", aiff, wav], check=True)
    with wave.open(wav) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    return data


def main():
    voices = [tts(i, t) for i, (_, t) in enumerate(SCENES)]
    LEAD, TAIL = 0.45, 0.75
    durs = [len(v) / SR + LEAD + TAIL for v in voices]
    scenes = []
    for (vis, _), dur in zip(SCENES, durs):
        kind, img, s, e, text = vis
        scenes.append((kind, img, s, e, int(dur * FPS), text))
    # аудиодорожка с учётом кроссфейдов (каждый переход «съедает» FADE секунд)
    total = sum(durs) - FADE * (len(durs) - 1)
    track = np.zeros(int((total + 1) * SR), dtype=np.float32)
    t0 = 0.0
    for v, dur in zip(voices, durs):
        a = int((t0 + LEAD) * SR)
        track[a:a + len(v)] += v
        t0 += dur - FADE
    wav_path = f"{AUD}/voice.wav"
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.clip(track, -32767, 32767).astype(np.int16).tobytes())
    silent = OUTFILE.replace(".mp4", ".noaudio.mp4")
    vdur = render(scenes, silent, crf=22)
    ff = mv.imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", silent, "-i", wav_path, "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "160k", "-shortest", "-movflags", "+faststart", OUTFILE], check=True)
    os.remove(silent)
    print(f"video {vdur:.1f}s, audio {total:.1f}s")


if __name__ == "__main__":
    main()
