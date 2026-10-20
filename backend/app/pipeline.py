"""Конвейер /api/recommend: разбор → фильтры → поиск → ранжирование → генерация → валидатор → маршрут."""
from __future__ import annotations

import asyncio
import re
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import config, geo, llm
from .data import store
from .generate import GEN_SYSTEM, build_user_prompt
from . import needs as needs_mod
from . import where as where_mod
from .guards import (closed_mention_warning, danger_warning, mentioned_pois,
                     out_of_area_warning)
from .models import RecommendRequest
from .parse import PARSE_SYSTEM, detect_lang, merge_llm, rule_parse
from .rank import HERE_PENALTY_INTENTS, Ctx, _not_destination, hard_filter, make_cand, rank
from .route import build_route
from . import search as search_mod
from .search import index
from .validate import validate
from .weather import get_weather

log = logging.getLogger("seruen.pipeline")
TZ = timezone(timedelta(hours=config.TZ_OFFSET_H))
CENTER_LANDMARK = (51.1283, 71.4305)  # Байтерек

WEEKDAYS = {"ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
            "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "kk": ["дүйсенбі", "сейсенбі", "сәрсенбі", "бейсенбі", "жұма", "сенбі", "жексенбі"]}
MODE_LABEL = {"ru": {"walk": "пешком", "car": "на машине/такси", "transit": "общественный транспорт"},
              "en": {"walk": "on foot", "car": "by car/taxi", "transit": "public transport"},
              "kk": {"walk": "жаяу", "car": "көлікпен/таксимен", "transit": "қоғамдық көлік"}}


def parse_client_time(s: str | None) -> datetime:
    if s:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            return dt.astimezone(TZ)
        except ValueError:
            pass
    return datetime.now(TZ)


def L(lang: str, ru: str, en: str, kk: str) -> str:
    return {"ru": ru, "en": en, "kk": kk}.get(lang, ru)


async def recommend(req: RecommendRequest) -> dict:
    t0 = time.monotonic()
    rid = uuid.uuid4().hex[:12]
    pois = store.get()
    index.ensure()
    search_mod.mark_user_activity()  # фоновая сборка индекса уступает живым запросам
    query = req.query.strip()
    lang = req.lang or (detect_lang(query) if query else "ru")
    rules = rule_parse(query, lang)
    when = parse_client_time(req.client_time)
    warnings: list[str] = []

    if req.location:
        start = (round(req.location.lat, 3), round(req.location.lon, 3))  # на всякий случай огрубляем и здесь
    else:
        start = CENTER_LANDMARK
        warnings.append(L(lang, "Локация не передана — расстояния считаются от Байтерека.",
                          "No location given — distances are from Baiterek.",
                          "Орын берілмеді — қашықтық Бәйтеректен есептеледі."))

    # 1. Разбор запроса (LLM) параллельно с погодой
    llm_ms = 0
    parse_task = None
    # LLM-разбор нужен, когда правилам не за что зацепиться (или не русский) — экономим квоту
    weak_rules = rules["intent"] == "other" and not rules["constraints"] and not rules["needs"] or lang != "ru"
    if query and llm.get_provider() and (config.LLM_PARSE_MODE == "always" or
                                         config.LLM_PARSE_MODE == "auto" and weak_rules):
        parse_task = asyncio.wait_for(asyncio.to_thread(
            llm.complete_json, PARSE_SYSTEM, query, temperature=0.0, max_tokens=300,
            timeout=config.LLM_PARSE_TIMEOUT_S, total=config.LLM_PARSE_TIMEOUT_S, purpose="parse"),
            timeout=config.LLM_PARSE_TIMEOUT_S + 0.3)
    weather_task = get_weather(when, rules.get("temperature_hint"),
                               req.weather_override.model_dump() if req.weather_override else None)
    llm_parsed = None
    if parse_task:
        res, weather = await asyncio.gather(parse_task, weather_task, return_exceptions=True)
        if isinstance(res, llm.LLMResult):
            llm_parsed, llm_ms = res.data, res.latency_ms
        if isinstance(weather, Exception):
            weather = None
    else:
        weather = await weather_task
    parsed = merge_llm(rules, llm_parsed)

    # 2. Явные фильтры UI важнее текста
    f = req.filters
    with_kids = f.with_kids if f.with_kids is not None else parsed["companions"] == "kids"
    access = f.accessibility if f.accessibility is not None else "accessibility" in parsed["constraints"]
    cold = bool(weather and weather.cold)
    # «в тепле» + мороз/ветер → только помещения (явный фильтр UI важнее)
    indoor_only = f.indoor_only if f.indoor_only is not None else ("indoor" in parsed["constraints"] and cold)
    near_airport = geo.haversine_m(*start, *config.AIRPORT) < 3000
    flight = "flight_soon" in parsed["constraints"] or near_airport
    mode = req.mode
    notes: list[str] = []
    if flight and mode == "walk":
        mode = "car"
        notes.append(L(lang, "до вылета мало времени → режим такси", "flight soon → taxi mode", "ұшуға аз уақыт → такси"))
    budget = f.time_budget_min or parsed["time_budget_min"]
    budget_explicit = budget is not None
    if flight:
        budget = budget or 120
        available = max(15, budget - config.FLIGHT_BUFFER_MIN)
        one_way = max(5, (available - 15) / 2)
        radius = geo.radius_for_budget(int(one_way / config.ONE_WAY_SHARE), mode)
    else:
        budget = budget or config.DEFAULT_BUDGET_MIN
        available = budget
        radius = geo.radius_for_budget(budget, mode, walk_intent=parsed["intent"] == "walk")
        if not budget_explicit and mode == "walk" and re.search(r"недалеко|рядом|поблизости|близко|nearby|near me|жақын", query.lower()):
            radius = min(radius, 1200)
        if cold and mode == "walk":
            radius = max(config.MIN_RADIUS_M, int(radius * 0.6))
            notes.append(L(lang, "холодно — пешие расстояния сокращены", "cold — shorter walking distances",
                           "суық — жаяу қашықтық қысқартылды"))
    parsed_out = {**parsed, "time_budget_min": budget if (budget_explicit or flight) else parsed["time_budget_min"]}

    needs = list(parsed.get("needs") or [])
    shopping = needs_mod.is_shopping(needs)
    if needs:  # ключевые слова потребности помогают BM25 внутри подходящих мест
        parsed_out["keywords"] = list(dict.fromkeys(
            [needs_mod.BY_KEY[k].label["ru"] for k in needs] + parsed_out["keywords"]))[:10]
    ctx = Ctx(start=start, when=when, mode=mode, lang=lang, budget=budget, budget_explicit=budget_explicit,
              radius=radius, parsed=parsed, with_kids=with_kids, accessibility=access, indoor_only=indoor_only,
              categories=list(f.categories or []), flight=flight, available=available, weather=weather,
              needs=needs, brand=needs_mod.brand(query) if needs else None,
              want_budget=needs_mod.wants_budget(query))

    # 3. Жёсткие фильтры
    cands, stats = hard_filter(pois, ctx)
    for w in (out_of_area_warning(query, start, lang), danger_warning(query, lang)):
        if w:
            warnings.append(w)
    mentioned = mentioned_pois(query, pois)
    for p in mentioned:
        mc = make_cand(p, ctx)
        if mc.open.state == "closed" or not mc.open.fits_visit:
            warnings.append(closed_mention_warning(p, mc.open.label, lang))
    if needs and not cands:
        cands = need_fallback(pois, ctx, needs, warnings, notes)
    elif not cands:  # лучшее из доступного: ближайшие не закрытые
        base = sorted((p for p in pois if not _not_destination(p) and p.get("category") not in needs_mod.SHOP_CATEGORIES),
                      key=lambda p: geo.haversine_m(*start, p["lat"], p["lon"]))[:12]
        all_c = [make_cand(p, ctx) for p in base]
        all_c.sort(key=lambda c: c.travel_min + c.back_min)  # при вылете учитываем и дорогу обратно
        open_c = [c for c in all_c if c.open.state != "closed"] or all_c
        within = [c for c in open_c if c.travel_min <= available]
        cands = (within or open_c[:1])[:3]
        warnings.append(L(lang, "Под все условия ничего не нашлось — показываю ближайшие варианты; проверьте часы и время в пути.",
                          "Nothing matches all conditions — showing the nearest options; check hours and travel time.",
                          "Барлық шартқа сай орын табылмады — ең жақын нұсқалар көрсетілді."))
        if not within and cands:
            c0 = cands[0]
            warnings.append(L(lang,
                f"Рядом ничего нет: ближайшее место — «{c0.poi['name']}», {c0.dist_m / 1000:.1f} км (~{c0.travel_min} мин), это дальше вашего бюджета {available} мин.",
                f"Nothing nearby: the closest place is “{c0.poi['name']}”, {c0.dist_m / 1000:.1f} km (~{c0.travel_min} min), beyond your {available}-min budget.",
                f"Жақын маңда ештеңе жоқ: ең жақыны — «{c0.poi['name']}», {c0.dist_m / 1000:.1f} км (~{c0.travel_min} мин)."))
    if flight:
        t_center = geo.travel_min(geo.haversine_m(*start, *CENTER_LANDMARK), mode)
        back = geo.travel_min(geo.haversine_m(*CENTER_LANDMARK, *config.AIRPORT), mode)
        if t_center + back + 20 > available:
            warnings.append(L(lang,
                f"До центра (Байтерек) ~{t_center} мин на такси, обратно в аэропорт ~{back} мин: с запасом "
                f"{config.FLIGHT_BUFFER_MIN} мин до вылета в центр не успеть — предлагаю места ближе.",
                f"Downtown (Baiterek) is ~{t_center} min by taxi and ~{back} min back to the airport: with a "
                f"{config.FLIGHT_BUFFER_MIN}-min buffer you can't make it — here are closer options.",
                f"Орталыққа ~{t_center} мин, әуежайға қайту ~{back} мин: үлгермейсіз — жақын орындар ұсынылады."))

    # 4. Поиск и ранжирование
    expand = list(parsed["constraints"]) + [parsed["intent"]] + (["kids"] if with_kids else [])
    rel = await asyncio.to_thread(index.scores, " ".join([query] + parsed["keywords"]), expand,
                                  [c.poi["id"] for c in cands])  # эмбеддинг запроса — сетевой вызов, не держим loop
    named = {p["id"] for p in mentioned if geo.haversine_m(*start, p["lat"], p["lon"]) > 300}
    # место, где пользователь уже стоит (метка локации/запрос + < 250 м): при прогулке — только запасной вариант
    if parsed["intent"] in HERE_PENALTY_INTENTS and not indoor_only and not needs:
        at = {p["id"] for p in mentioned_pois(f"{req.location_label or ''} {query}", pois)}
        walk = parsed["intent"] == "walk"
        for c in cands:  # прогулка: всё, что в ~200 м от пользователя, — «вы уже здесь», максимум идея
            c.here = c.poi["id"] not in named and (c.poi["id"] in at and c.dist_m < 250 or walk and c.dist_m < 200)
    if parsed["intent"] == "walk" and not needs and not cold:
        walkable = [c for c in cands if is_walkable(c.poi)]
        if len(walkable) >= 2:  # «прогуляться 30–60 мин» — парки, бульвары, набережные, видовые места
            cands = walkable
    for c in cands:
        c.relevance = 1.5 if c.poi["id"] in named else rel.get(c.poi["id"], 0.0)
    top = rank(cands, ctx)

    # 5. Генерация (только из кандидатов) → 6. валидатор
    llm_data, llm_info = None, {"provider": "none", "model": None, "latency_ms": 0}
    if llm.get_provider() and top:
        try:
            res = await asyncio.wait_for(asyncio.to_thread(
                llm.complete_json, GEN_SYSTEM, build_user_prompt(query, ctx, top), temperature=0.4,
                max_tokens=1500), timeout=config.LLM_TOTAL_BUDGET_S + 0.5)
            llm_data = res.data
            llm_info = {"provider": res.provider, "model": res.model, "latency_ms": llm_ms + res.latency_ms}
        except (llm.LLMError, asyncio.TimeoutError) as e:
            log.warning("[%s] generation degraded: %s", rid, type(e).__name__ + ": " + str(e)[:120])
    if not top:
        pass  # кандидатов нет — LLM не нужен, причина уже в warnings
    elif llm_data is None and llm.get_provider() and llm.quota_limited():
        warnings.append(L(lang, "Лимит запросов к ИИ-модели временно исчерпан — подборка собрана по ранжированию базы, тексты шаблонные.",
                          "AI request quota temporarily exhausted — picks come from database ranking with template texts.",
                          "ЖИ сұраныс лимиті уақытша таусылды — таңдау база рейтингі бойынша жасалды."))
    elif llm_data is None:
        warnings.append(L(lang, "ИИ-модель недоступна — подборка собрана по ранжированию базы, тексты шаблонные.",
                          "AI model unavailable — picks come from database ranking with template texts.",
                          "ЖИ моделі қолжетімсіз — таңдау база рейтингі бойынша жасалды."))
    recs, ideas, vwarn = validate(llm_data, top, ctx)
    here_ids = {c.poi["id"] for c in top if c.here}
    if here_ids and any(r["poi_id"] not in here_ids for r in recs):
        for r in [r for r in recs if r["poi_id"] in here_ids]:
            recs.remove(r)  # пользователь уже здесь — переносим в идеи как запасной вариант
            ideas.append({"source_type": "generated_idea", "text": L(lang,
                f"Если замёрзнете или устанете — вы рядом с «{r['name']}», можно вернуться туда.",
                f"If you get cold or tired, “{r['name']}” is right where you are.",
                f"Тоңып не шаршасаңыз — «{r['name']}» жаныңызда.")})
    warnings += vwarn

    top_by_id = {c.poi["id"]: c for c in top}
    unknown = sum(1 for r in recs if r["open_status"]["state"] == "unknown"
                  and not top_by_id[r["poi_id"]].open.outdoor_area)
    if unknown:
        warnings.append(L(lang, f"Часы работы {unknown} мест(а) неизвестны — уточните перед выходом.",
                          f"Opening hours of {unknown} place(s) are unknown — check before going.",
                          f"{unknown} орынның жұмыс уақыты белгісіз — алдын ала нақтылаңыз."))
    if stats.get("closed"):
        notes.append(L(lang, f"скрыто закрытых к приходу: {stats['closed']}", f"hidden as closed on arrival: {stats['closed']}",
                       f"жабық орындар жасырылды: {stats['closed']}"))
    if stats.get("guess_closed"):
        notes.append(L(lang, f"скрыто без часов, вероятно закрытых в это время: {stats['guess_closed']}",
                       f"hidden (no hours, likely closed now): {stats['guess_closed']}",
                       f"уақыты жоқ, жабық болуы мүмкін: {stats['guess_closed']}"))
    warnings += ctx.warnings

    # 7. Маршрут
    route = None
    route_asked = bool(re.search(r"маршрут|route|по пути|обойти|маршрут", query.lower()))
    if needs and ctx.want_budget and recs and not any("budget" in (store.by_id.get(r["poi_id"], {}).get("tags") or [])
                                                      for r in recs):
        warnings.append(L(lang, "Данных о ценах в базе нет — показываю ближайшие подходящие места; уровень цен уточните на месте.",
                          "We have no price data — showing the nearest matching places; check prices on site.",
                          "Бағалар туралы дерек жоқ — ең жақын орындар көрсетілді."))
    # маршрут: прогулкам и досугу; магазинам и «бассейн/кино…» — только если попросили
    if req.want_route and recs and (not needs or route_asked):
        route, _, rwarn = await build_route(start, recs, mode, available if (budget_explicit or flight) else None, lang)
        warnings += rwarn

    resp = {
        "request_id": rid,
        "context_used": context_used(req, ctx, start, lang, notes),
        "parsed_intent": {k: parsed_out[k] for k in ("intent", "time_budget_min", "companions", "constraints", "keywords")},
        "recommendations": recs,
        "ideas": ideas,
        "route": route,
        "warnings": [w for w in dict.fromkeys(warnings) if w],
        "llm": llm_info,
    }
    log.info("[%s] intent=%s cands=%d recs=%d llm=%s area=%.2f,%.2f %dms", rid, parsed["intent"], len(cands),
             len(recs), llm_info["provider"], geo.round_coord(start[0]), geo.round_coord(start[1]),
             int((time.monotonic() - t0) * 1000))
    return resp


WALK_CATEGORIES = {"park", "viewpoint", "landmark", "monument"}
NOT_WALK = {"cafe", "restaurant", "bar", "nightlife", "mall", "playground", "cinema"} | needs_mod.SHOP_CATEGORIES


def is_walkable(p: dict) -> bool:
    if p.get("category") in NOT_WALK:
        return False
    return p.get("category") in WALK_CATEGORIES or bool({"walk", "view"} & set(p.get("tags") or []))


def need_fallback(pois: list[dict], ctx: Ctx, needs: list[str], warnings: list[str], notes: list[str]) -> list:
    """Рядом нет того, что просили: расширяем до 10 км (такси) или честно говорим, что в базе этого нет.
    Никаких «ближайших кафе» вместо бассейна."""
    lang, label = ctx.lang, needs_mod.labels(needs, ctx.lang)
    pool = [p for p in pois if not _not_destination(p) and needs_mod.matches_any(p, needs, ctx.brand)]
    if not pool:
        warnings.append(L(lang, f"В нашей базе нет мест для: {label}. Не буду подставлять что-то другое — "
                                f"попробуйте уточнить запрос или выбрать категорию.",
                          f"Our database has no places for: {label}. I won't substitute something else.",
                          f"Біздің базада мына орындар жоқ: {label}."))
        return []
    walk_mode = ctx.mode == "walk"
    if walk_mode:
        ctx.mode = "car"
    ctx.radius, ctx.budget_explicit = config.NEED_MAX_RADIUS_M, False
    cands, _ = hard_filter(pois, ctx)
    if cands:
        c0 = min(cands, key=lambda c: c.dist_m)
        if walk_mode:
            notes.append(L(lang, "пешком рядом нет — считаю время на такси", "nothing within walking distance — taxi times",
                           "жаяу жақын жерде жоқ — такси уақыты"))
        warnings.append(L(lang,
            f"Пешком рядом нет: ближайший вариант ({label}) — «{c0.poi['name']}», {c0.dist_m / 1000:.1f} км, ~{c0.travel_min} мин на такси.",
            f"Nothing within walking distance: the closest ({label}) is “{c0.poi['name']}”, {c0.dist_m / 1000:.1f} km, ~{c0.travel_min} min by taxi.",
            f"Жаяу жақын жерде жоқ: ең жақыны ({label}) — «{c0.poi['name']}», {c0.dist_m / 1000:.1f} км, такси ~{c0.travel_min} мин."))
        return cands
    nearest = make_cand(min(pool, key=lambda p: geo.haversine_m(*ctx.start, p["lat"], p["lon"])), ctx)
    if nearest.open.state == "closed" or not nearest.open.fits_visit:
        warnings.append(L(lang,
            f"Ближайший вариант ({label}) — «{nearest.poi['name']}», {nearest.dist_m / 1000:.1f} км — к вашему приходу закрыт: {nearest.open.label}.",
            f"The closest ({label}) — “{nearest.poi['name']}”, {nearest.dist_m / 1000:.1f} km — is closed when you arrive: {nearest.open.label}.",
            f"Ең жақыны ({label}) — «{nearest.poi['name']}» — жабық: {nearest.open.label}."))
        return []
    warnings.append(L(lang,
        f"Ближайший вариант ({label}) — «{nearest.poi['name']}», {nearest.dist_m / 1000:.1f} км (~{nearest.travel_min} мин на такси): это далеко.",
        f"The closest ({label}) is “{nearest.poi['name']}”, {nearest.dist_m / 1000:.1f} km (~{nearest.travel_min} min by taxi): far away.",
        f"Ең жақыны ({label}) — «{nearest.poi['name']}», {nearest.dist_m / 1000:.1f} км: алыс."))
    return [nearest]


_MY_LOCATION = {"", "моя геолокация", "моё местоположение", "мое местоположение", "я здесь", "текущее местоположение",
                "my location", "current location", "менің орным", "геолокация"}


def context_used(req: RecommendRequest, ctx: Ctx, start, lang: str, notes: list[str]) -> dict:
    if req.location and (req.location_label or "").strip().lower() in _MY_LOCATION | {""}:
        w = where_mod.where(*start, lang)  # адрес по нашей базе: «у «Байтерек», бульвар Нуржол, 14»
        loc = L(lang, f"≈ {w['label']} (точность ~100 м)", f"≈ {w['label']} (~100 m precision)",
                f"≈ {w['label']} (~100 м дәлдік)")
    elif req.location_label:
        addr = where_mod.where(*start, lang)["address"] if req.location else None
        place = f"{req.location_label}, {addr}" if addr else req.location_label
        loc = L(lang, f"≈ район {place} (точность ~100 м)", f"≈ {place} area (~100 m precision)",
                f"≈ {place} маңы (~100 м дәлдік)")
    else:
        loc = L(lang, "не передана (считаем от Байтерека)", "not provided (using Baiterek)", "берілмеді (Бәйтерек)")
    p = ctx.parsed
    fl: list[str] = []
    if ctx.budget_explicit or ctx.flight:
        fl.append(L(lang, f"бюджет {ctx.budget} мин", f"budget {ctx.budget} min", f"уақыт {ctx.budget} мин"))
    else:
        fl.append(L(lang, f"бюджет не указан — беру ~{ctx.budget} мин", f"no budget given — assuming ~{ctx.budget} min",
                    f"уақыт көрсетілмеген — ~{ctx.budget} мин"))
    if ctx.flight:
        fl.append(L(lang, f"запас {config.FLIGHT_BUFFER_MIN} мин до вылета, остаётся {ctx.available} мин с дорогой",
                    f"{config.FLIGHT_BUFFER_MIN}-min buffer before the flight, {ctx.available} min left incl. travel",
                    f"ұшуға дейін {config.FLIGHT_BUFFER_MIN} мин қор"))
    if ctx.with_kids:
        fl.append(L(lang, "с детьми", "with kids", "балалармен"))
    if ctx.accessibility:
        fl.append(L(lang, "доступность для коляски", "wheelchair access", "арбамен қолжетімді"))
    if ctx.indoor_only:
        fl.append(L(lang, "только в помещении", "indoor only", "тек ғимарат ішінде"))
    if ctx.categories:
        fl.append(L(lang, "категории: ", "categories: ", "санаттар: ") + ", ".join(ctx.categories))
    if ctx.needs:
        fl.append(L(lang, "нужно: ", "looking for: ", "қажет: ") + needs_mod.labels(ctx.needs, lang)
                  + L(lang, " (только подходящие места)", " (matching places only)", " (тек сәйкес орындар)"))
    if ctx.brand:
        fl.append(L(lang, f"сеть: {ctx.brand}", f"brand: {ctx.brand}", f"желі: {ctx.brand}"))
    soft = [c for c in p["constraints"] if c not in ("flight_soon", "accessibility")]
    if soft:
        fl.append(L(lang, "пожелания: ", "preferences: ", "тілектер: ") + ", ".join(soft))
    if ctx.weather and ctx.weather.bad:
        fl.append(L(lang, "погода: приоритет местам в помещении", "weather: indoor places preferred", "ауа райы: жабық орындар"))
    h = ctx.when.hour
    if h >= 22 or h < 6:
        fl.append(L(lang, "ночь: места, открытые допоздна", "night: late-open places", "түн: кеш жабылатын орындар"))
    fl += notes
    return {
        "location": loc,
        "time": f"{WEEKDAYS.get(lang, WEEKDAYS['ru'])[ctx.when.weekday()]}, {ctx.when:%H:%M}",
        "weather": ctx.weather.label(lang) if ctx.weather else L(lang, "нет данных", "no data", "дерек жоқ"),
        "mode": MODE_LABEL.get(lang, MODE_LABEL["ru"])[ctx.mode],
        "radius_m": int(ctx.radius),
        "filters": fl,
        "data_note": L(lang,
            "Используются: огрублённая локация (~100 м), время, фильтры и текст запроса. Координаты не сохраняются и не пишутся в логи; погода запрашивается по центру города.",
            "Used: coarse location (~100 m), time, filters and your query. Coordinates are not stored or logged; weather is fetched for the city centre.",
            "Қолданылады: шамамен орын (~100 м), уақыт, сүзгілер. Координаттар сақталмайды."),
    }
