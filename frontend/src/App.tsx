import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, LoaderCircle, LocateFixed, MapPin, RotateCcw, SlidersHorizontal, X } from 'lucide-react'
import MapView from './components/MapView'
import Controls, { type ControlsState } from './components/Controls'
import Results from './components/Results'
import ContextUsed from './components/ContextUsed'
import { ApiError, USE_MOCK, fetchCategoryPhotos, fetchHealth, fetchPois, fetchPresets, fetchWhere, recommend } from './api'
import Ornament from './components/Ornament'
import ScrollStrip from './components/ScrollStrip'
import { Credit } from './components/Photo'
import { presetVisual } from './components/Icons'
import { FALLBACK_PHOTOS, imgSrc } from './photos'
import { isNightIso } from './hours'
import { coarsen, isoClock, slotToIso } from './geo'
import { DICTS, type Dict } from './i18n'
import type { CategoryPhotos, Lang, LatLon, Poi, Preset, RecommendRequest, RecommendResponse, WhereInfo } from './types'

const LANG_KEY = 'seruen.lang'
// ?static=1 — без плавных анимаций (для скриншотов headless-браузером)
const STATIC = new URLSearchParams(window.location.search).get('static') === '1'
const LANGS: { id: Lang; label: string }[] = [
  { id: 'ru', label: 'RU' },
  { id: 'kk', label: 'ҚАЗ' },
  { id: 'en', label: 'EN' },
]

function loadLang(): Lang {
  const q = new URLSearchParams(window.location.search).get('lang')
  if (q === 'ru' || q === 'kk' || q === 'en') return q
  try {
    const v = localStorage.getItem(LANG_KEY)
    if (v === 'ru' || v === 'kk' || v === 'en') return v
  } catch {
    /* localStorage недоступен — не страшно */
  }
  return 'ru'
}

// Спец-метки локации: переводятся при показе, на сервер не отправляются.
const PICKED = '__picked__'
const GEO = '__geo__'

interface ActivePreset {
  id: string
  query: string
  controls: ControlsState
  budget: number | null
  categories: string[]
}

const DEFAULT_CONTROLS: ControlsState = {
  slot: 'now',
  presetTime: null,
  withKids: false,
  accessibility: false,
  groupSize: 1,
  indoorOnly: false,
  mode: 'walk',
  weather: null,
}

export default function App() {
  const [lang, setLang] = useState<Lang>(loadLang)
  const t = DICTS[lang]

  const [location, setLocation] = useState<LatLon>({ lat: 51.089, lon: 71.41 })
  const [locationLabel, setLocationLabel] = useState<string>('Mega Silk Way')
  const [query, setQuery] = useState('')
  // Настройки, выбранные пользователем сам, и настройки активного пресета — раздельно:
  // пресет действует, только пока он активен (его запрос не изменён), потом — снова пользовательские.
  const [userControls, setUserControls] = useState<ControlsState>(DEFAULT_CONTROLS)
  const [userBudget, setUserBudget] = useState<number | null>(null)
  const [preset, setPreset] = useState<ActivePreset | null>(null)
  const controls = preset?.controls ?? userControls
  const timeBudget = preset ? preset.budget : userBudget
  const activePreset = preset?.id ?? null
  const [presets, setPresets] = useState<Preset[]>([])
  const [history, setHistory] = useState<string[]>([])

  // Ответ хранится вместе с запросом, на который он пришёл, — «Что учтено» и режим берутся из этой пары.
  const [shown, setShown] = useState<{ req: RecommendRequest; res: RecommendResponse } | null>(null)
  const result = shown?.res ?? null
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const [focusIndex, setFocusIndex] = useState<number | null>(null)
  const [backendUp, setBackendUp] = useState<boolean | null>(null)
  const [pois, setPois] = useState<Poi[]>([])
  const [geoAsk, setGeoAsk] = useState(false)
  const [geoErr, setGeoErr] = useState(false)
  const [paramsOpen, setParamsOpen] = useState(false)
  const [photos, setPhotos] = useState<CategoryPhotos>(FALLBACK_PHOTOS)

  const lastReq = useRef<{ req: RecommendRequest; presetId?: string } | null>(null)
  const resultsRef = useRef<HTMLDivElement>(null)
  const reqSeq = useRef(0)

  useEffect(() => {
    try {
      localStorage.setItem(LANG_KEY, lang)
    } catch {
      /* ignore */
    }
    document.documentElement.lang = lang === 'kk' ? 'kk' : lang
  }, [lang])

  useEffect(() => {
    fetchPresets()
      .then(setPresets)
      .catch(() => setPresets([]))
    fetchCategoryPhotos().then(setPhotos)
    if (!USE_MOCK) {
      fetchHealth().then(setBackendUp)
      fetchPois([51.0, 71.3, 51.22, 71.6])
        .then(setPois)
        .catch(() => setPois([]))
    }
  }, [])

  // Deep-link для демо/видео: ?preset=<id>&lang=kk — сразу запускает сценарий.
  const autoRan = useRef(false)
  useEffect(() => {
    if (autoRan.current || presets.length === 0) return
    autoRan.current = true
    const params = new URLSearchParams(window.location.search)
    const id = params.get('preset')
    const p = id && presets.find((x) => x.id === id)
    if (p) applyPreset(p)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [presets])

  const run = useCallback(async (req: RecommendRequest, presetId?: string) => {
    const seq = ++reqSeq.current
    lastReq.current = { req, presetId }
    setLoading(true)
    setError(null)
    setHovered(null)
    setFocusIndex(null)
    setHistory((h) => [req.query, ...h.filter((q) => q !== req.query)].slice(0, 5))
    // В static-режиме на узком экране не скроллим документ: headless Chrome снимает такой кадр пустым.
    if (!STATIC || window.innerWidth >= 1024)
      requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: STATIC ? 'instant' : 'smooth', block: 'start' }))
    try {
      const res = await recommend(req, presetId)
      if (seq !== reqSeq.current) return // ответ на устаревший запрос — игнорируем
      setShown({ req, res })
      if (!STATIC || window.innerWidth >= 1024)
        requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: STATIC ? 'instant' : 'smooth', block: 'start' }))
    } catch (e) {
      if (seq !== reqSeq.current) return
      setShown(null)
      setError(e instanceof ApiError ? e : new ApiError('unknown', String(e)))
    } finally {
      if (seq === reqSeq.current) setLoading(false)
    }
  }, [])

  const buildRequest = (
    q: string,
    loc: LatLon,
    label: string,
    c: ControlsState,
    budget: number | null,
    categories: string[] = [],
  ): RecommendRequest => ({
    query: q,
    location: coarsen(loc),
    // Для геолокации и точки на карте названия нет — сервер сам напишет «≈ ваша локация».
    location_label: label === PICKED || label === GEO ? undefined : label,
    client_time: c.presetTime ?? slotToIso(c.slot),
    lang,
    mode: c.mode,
    filters: {
      with_kids: c.withKids,
      accessibility: c.accessibility,
      group_size: c.groupSize,
      time_budget_min: budget,
      indoor_only: c.indoorOnly ? true : null,
      categories,
    },
    want_route: true,
    ...(c.weather ? { weather_override: c.weather } : {}),
  })

  // Новый запрос можно отправить и во время загрузки: он вытесняет предыдущий (reqSeq).
  const submit = (q = query) => {
    const text = q.trim()
    if (!text) return
    setQuery(text)
    // Свой текст (не запрос пресета) — пресет больше не действует, берём выбор пользователя.
    const keepPreset = preset && preset.query === text ? preset : null
    if (!keepPreset) setPreset(null)
    const c = keepPreset ? keepPreset.controls : userControls
    const budget = keepPreset ? keepPreset.budget : userBudget
    run(buildRequest(text, location, locationLabel, c, budget, keepPreset?.categories), keepPreset?.id)
  }

  // Параметры поменяли при показанной выдаче — перезапрашиваем тот же запрос с новыми параметрами (debounce 600 мс).
  const refreshTimer = useRef<number | undefined>(undefined)
  const scheduleRefresh = (c: ControlsState) => {
    const last = lastReq.current
    if (!last) return
    window.clearTimeout(refreshTimer.current)
    refreshTimer.current = window.setTimeout(() => {
      const req: RecommendRequest = {
        ...last.req,
        client_time: c.presetTime ?? slotToIso(c.slot),
        mode: c.mode,
        filters: {
          ...last.req.filters,
          with_kids: c.withKids,
          accessibility: c.accessibility,
          group_size: c.groupSize,
          indoor_only: c.indoorOnly ? true : null,
        },
      }
      delete req.weather_override
      if (c.weather) req.weather_override = c.weather
      run(req, last.presetId)
    }, 600)
  }

  const changeControls = (next: ControlsState, refresh = true) => {
    if (refresh && (shown || loading)) scheduleRefresh(next)
    if (!preset) return setUserControls(next)
    // Правка поверх пресета: меняем и сценарий, и выбор пользователя (только изменённые поля).
    const changed = Object.fromEntries(
      (Object.keys(next) as (keyof ControlsState)[]).filter((k) => next[k] !== preset.controls[k]).map((k) => [k, next[k]]),
    )
    setPreset({ ...preset, controls: next })
    setUserControls((u) => ({ ...u, ...changed }))
  }

  /** «Ничего не нашли» → расширить поиск: повторяем последний запрос с изменениями, видимыми в панели. */
  const widen = (kind: 'budget' | 'car') => {
    const last = lastReq.current
    if (!last) return
    const req: RecommendRequest = structuredClone(last.req)
    if (kind === 'budget') {
      const b = Math.max(120, (req.filters.time_budget_min ?? 60) * 2)
      req.filters.time_budget_min = b
      if (preset) setPreset({ ...preset, budget: b })
      else setUserBudget(b)
    } else {
      req.mode = 'car'
      changeControls({ ...controls, mode: 'car' }, false)
    }
    run(req, last.presetId)
  }

  const applyPreset = (p: Preset) => {
    const f = p.filters ?? {}
    // Пресет задаёт всё сам, поверх умолчаний, а не поверх прошлого состояния.
    const c: ControlsState = {
      ...DEFAULT_CONTROLS,
      presetTime: p.client_time ?? null,
      withKids: !!f.with_kids,
      accessibility: !!f.accessibility,
      groupSize: f.group_size ?? 1,
      indoorOnly: !!f.indoor_only,
      mode: p.mode ?? (/airport|аэропорт/i.test(p.id + p.label) ? 'car' : 'walk'),
      weather: p.weather_override ?? null,
    }
    const budget = f.time_budget_min ?? null
    const loc = { lat: p.location.lat, lon: p.location.lon }
    const label = p.location_label ?? p.label
    setLocation(loc)
    setLocationLabel(label)
    setQuery(p.query)
    setPreset({ id: p.id, query: p.query, controls: c, budget, categories: f.categories ?? [] })
    run(buildRequest(p.query, loc, label, c, budget, f.categories ?? []), p.id)
  }

  const labelText = (l: string) => (l === PICKED ? t.pickedPoint : l === GEO ? t.myLocation : l)

  const pickLocation = (p: LatLon, label = PICKED) => {
    setLocation(coarsen(p))
    setLocationLabel(label)
    setPreset(null)
  }

  const askGeo = () => {
    setGeoAsk(false)
    setGeoErr(false)
    if (!navigator.geolocation) return setGeoErr(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => pickLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude }, GEO),
      () => setGeoErr(true),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 600000 },
    )
  }

  // Смена языка при показанном ответе — перезапрашиваем, чтобы и рекомендации пришли на новом языке.
  const prevLang = useRef(lang)
  useEffect(() => {
    if (prevLang.current === lang) return
    prevLang.current = lang
    const last = lastReq.current
    if (last && result) run({ ...last.req, lang }, last.presetId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang])

  // «Назад» из выдачи к экрану запроса: кнопка, браузерная «Назад» (history state) и Esc. Запрос и параметры сохраняются.
  const pushedRef = useRef(false)
  const inResults = !!shown || loading || !!error
  const goIdle = () => {
    reqSeq.current++ // ответ на уже отправленный запрос больше не нужен
    window.clearTimeout(refreshTimer.current)
    setLoading(false)
    setShown(null)
    setError(null)
    setHovered(null)
    setFocusIndex(null)
    document.querySelector('aside')?.scrollTo({ top: 0 })
    window.scrollTo({ top: 0 })
  }
  const goBack = () => {
    if (pushedRef.current) window.history.back()
    else goIdle()
  }
  useEffect(() => {
    if (inResults && !pushedRef.current && !STATIC) {
      window.history.pushState({ seruen: 'results' }, '')
      pushedRef.current = true
    }
  }, [inResults])
  useEffect(() => {
    const onPop = () => {
      if (!pushedRef.current) return
      pushedRef.current = false
      goIdle()
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const goBackRef = useRef(goBack)
  goBackRef.current = goBack
  useEffect(() => {
    if (!inResults) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') goBackRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [inResults])

  const shownLoc = coarsen(location)
  const locKey = `${shownLoc.lat},${shownLoc.lon}`

  // Адрес точки старта (POST /api/where) — с debounce; устаревшие ответы отбрасываем, при ошибке — тихо координаты.
  const [where, setWhere] = useState<{ key: string; lang: Lang; info: WhereInfo } | null>(null)
  useEffect(() => {
    const ctrl = new AbortController()
    const id = setTimeout(() => {
      fetchWhere(shownLoc, lang, ctrl.signal)
        .then((info) => setWhere(info ? { key: locKey, lang, info } : null))
        .catch(() => {
          if (!ctrl.signal.aborted) setWhere(null)
        })
    }, 300)
    return () => {
      clearTimeout(id)
      ctrl.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locKey, lang])
  const here = where && where.key === locKey && where.lang === lang ? where.info : null
  const coordsText = `≈ ${shownLoc.lat.toFixed(3)}, ${shownLoc.lon.toFixed(3)}`
  const idle = !shown && !loading && !error
  // Время, которое уйдёт с запросом (пресет или выбор в «Параметрах»): вечер/ночь → «ночной город» на карте.
  const effTime = controls.presetTime ?? slotToIso(controls.slot)
  const night = isNightIso(effTime)
  // Плавный переход цветов включаем только на время смены день/ночь — в остальное время без лишних пересчётов стилей.
  const [themeSwitching, setThemeSwitching] = useState(false)
  const prevNight = useRef(night)
  useEffect(() => {
    if (prevNight.current === night) return
    prevNight.current = night
    setThemeSwitching(true)
    const id = window.setTimeout(() => setThemeSwitching(false), 700)
    return () => window.clearTimeout(id)
  }, [night])
  // Обложка — первое фото курированного списка (стабильно для демо и скриншотов).
  const hero = photos.hero[0] ?? null

  return (
    <div className="min-h-dvh bg-white lg:grid lg:h-dvh lg:grid-cols-[minmax(420px,520px)_1fr] xl:grid-cols-[600px_1fr]">
      {/* Карта: на мобиле — сверху (лист выдачи наезжает на неё), на десктопе — справа */}
      <section className="sticky top-0 z-0 h-[42vh] max-h-[460px] min-h-[280px] lg:order-2 lg:h-dvh lg:max-h-none">
        <MapView
          location={location}
          result={result}
          hovered={hovered}
          onHover={setHovered}
          onPick={(p) => pickLocation(p)}
          onMarkerClick={(i) => {
            setHovered(i)
            setFocusIndex(i)
          }}
          pois={pois}
          hint={t.locationHint}
          coarseLabel={t.locationCoarse}
          lang={lang}
          night={night}
          clientTime={effTime}
          nightLabel={t.nightLabel}
          hereLabel={`${t.youAreHere} · ${here?.label ?? coordsText}`}
        />
      </section>

      {/* Панель / bottom sheet */}
      <aside className={`${themeSwitching ? 'theme-anim' : ''} ${night ? 'theme-night' : ''} relative z-10 -mt-6 rounded-t-[28px] bg-white shadow-[0_-10px_30px_rgb(11_37_69/0.10)] lg:order-1 lg:mt-0 lg:overflow-y-auto lg:rounded-none lg:border-r lg:border-ink-100 lg:shadow-none`}>
        <div className="mx-auto mt-2.5 h-1.5 w-10 rounded-full bg-ink-200 lg:hidden" aria-hidden />

        <header className="z-20 flex items-center justify-between gap-3 bg-white px-5 pb-3 pt-3 sm:px-7 lg:sticky lg:top-0 lg:border-b lg:border-ink-100 lg:pt-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <Ornament className="h-6 w-12 shrink-0 text-sun-500" />
            <div className="min-w-0">
              <p className="font-display text-[22px] font-semibold leading-none text-ink-900">Seruen</p>
              <p className="mt-1 truncate text-[12px] text-ink-500">{t.tagline}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className="hidden items-center gap-1.5 text-[12px] text-ink-500 sm:inline-flex" title={USE_MOCK ? t.mockBadge : t.liveBadge}>
              <span className={`h-2 w-2 rounded-full ${USE_MOCK ? 'bg-sun-500' : backendUp === false ? 'bg-closed' : 'bg-open'}`} />
              {USE_MOCK ? t.mockBadge : t.liveBadge}
            </span>
            <div className="flex rounded-full border border-ink-200 p-0.5" role="group" aria-label="Language">
              {LANGS.map((l) => (
                <button
                  key={l.id}
                  onClick={() => setLang(l.id)}
                  aria-pressed={lang === l.id}
                  className={`rounded-full px-2.5 py-1 text-[13px] font-semibold transition ${
                    lang === l.id ? 'bg-ink-900 text-white' : 'text-ink-600 hover:text-ink-900'
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        <div className="space-y-6 px-5 pb-10 pt-2 sm:px-7">
          {idle && <Hero hero={hero} t={t} />}

          {/* Локация */}
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <div className="flex min-w-0 items-center gap-2.5">
              <MapPin className="h-5 w-5 shrink-0 text-teal-600" strokeWidth={1.8} />
              <div className="min-w-0">
                <p className="truncate text-[16px] font-semibold text-ink-900" title={here?.label}>
                  {here ? here.label : labelText(locationLabel)}
                </p>
                <p className="text-[12px] text-ink-400" title={coordsText}>
                  {here ? t.precision(here.precision_m ?? 100) : `${coordsText} · ${t.locationCoarse}`}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setGeoAsk(true)}
              className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 px-3 py-1.5 text-[13px] font-medium text-ink-800 hover:border-ink-400"
            >
              <LocateFixed className="h-4 w-4 text-teal-600" strokeWidth={1.8} />
              {t.myLocation}
            </button>
            {geoAsk && (
              <div className="w-full rounded-2xl border border-ink-100 p-4 text-[14px] text-ink-700">
                <p className="font-semibold text-ink-900">{t.geoConsentTitle}</p>
                <p className="mt-1 leading-snug">{t.geoConsentText}</p>
                <div className="mt-3 flex gap-2">
                  <button onClick={askGeo} className="rounded-full bg-ink-900 px-4 py-1.5 font-semibold text-white hover:bg-ink-800">
                    {t.allow}
                  </button>
                  <button onClick={() => setGeoAsk(false)} className="rounded-full px-4 py-1.5 font-semibold text-ink-600 hover:bg-ink-50">
                    {t.cancel}
                  </button>
                </div>
              </div>
            )}
            {geoErr && <p className="w-full text-[14px] text-closed">{t.geoError}</p>}
          </div>

          {/* Запрос */}
          <div>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                submit()
              }}
              className="rounded-2xl border border-ink-200 bg-white p-1.5 transition focus-within:border-teal-500 focus-within:ring-4 focus-within:ring-teal-100"
            >
              <textarea
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value)
                  if (preset && e.target.value.trim() !== preset.query) setPreset(null)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                rows={2}
                placeholder={t.queryPlaceholder}
                className="w-full resize-none bg-transparent px-3 py-2 text-[17px] leading-snug text-ink-900 outline-none placeholder:text-ink-400"
              />
              <div className="flex items-center justify-end gap-2 px-1 pb-1">
                <button
                  type="submit"
                  disabled={!query.trim()}
                  className="inline-flex items-center gap-2 rounded-xl bg-ink-900 px-5 py-2.5 text-[15px] font-semibold text-white transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:bg-ink-200 disabled:text-ink-400"
                >
                  {loading ? <LoaderCircle className="h-4 w-4 animate-spin" strokeWidth={2} /> : null}
                  {t.send}
                  {!loading && <ArrowRight className="h-4 w-4" strokeWidth={2} />}
                </button>
              </div>
            </form>

            <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
              <SendSummary t={t} c={controls} budget={timeBudget} fromPreset={!!preset} onClearBudget={() => setUserBudget(null)} />
              <button
                type="button"
                onClick={() => setParamsOpen((o) => !o)}
                aria-expanded={paramsOpen}
                className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-teal-700 hover:text-teal-600"
              >
                <SlidersHorizontal className="h-4 w-4" strokeWidth={1.8} />
                {t.params}
                <ChevronDown className={`h-4 w-4 transition ${paramsOpen ? 'rotate-180' : ''}`} strokeWidth={1.8} />
              </button>
            </div>
            {paramsOpen && (
              <div className="rise mt-3 rounded-2xl border border-ink-100 p-4">
                <Controls t={t} value={controls} onChange={changeControls} slotIso={slotToIso} />
              </div>
            )}

            {history.length > 1 && (
              <div className="mt-3 flex items-center gap-2 text-[13px]">
                <span className="shrink-0 text-ink-400">{t.history}:</span>
                <div className="min-w-0 flex-1">
                  <ScrollStrip className="gap-2">
                    {history.slice(1).map((h) => (
                      <button
                        key={h}
                        onClick={() => submit(h)}
                        title={h}
                        className="inline-flex max-w-[260px] shrink-0 items-center gap-1.5 rounded-full border border-ink-200 px-3 py-1.5 text-ink-700 transition hover:border-ink-400 hover:text-ink-900"
                      >
                        <RotateCcw className="h-3.5 w-3.5 shrink-0 text-ink-400" strokeWidth={1.8} />
                        <span className="truncate">{h}</span>
                      </button>
                    ))}
                  </ScrollStrip>
                </div>
              </div>
            )}
          </div>

          {/* Сценарии */}
          {presets.length > 0 &&
            (idle ? (
              <section>
                <h2 className="font-display text-[17px] font-semibold text-ink-900">{t.presets}</h2>
                <ul className="mt-2 divide-y divide-ink-100 border-y border-ink-100">
                  {presets.map((p) => {
                    const { Icon } = presetVisual(p.id, p.label)
                    return (
                      <li key={p.id}>
                        <button onClick={() => applyPreset(p)} className="group flex w-full items-center gap-4 py-3.5 text-left">
                          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-teal-50 text-teal-700 transition group-hover:bg-teal-500 group-hover:text-white">
                            <Icon className="h-5 w-5" strokeWidth={1.8} />
                          </span>
                          <span className="min-w-0 flex-1 text-[16px] font-medium leading-snug text-ink-900">{p.label}</span>
                          <ChevronRight className="h-5 w-5 shrink-0 text-ink-300 transition group-hover:translate-x-0.5 group-hover:text-ink-900" strokeWidth={1.8} />
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </section>
            ) : (
              <ScrollStrip className="gap-2">
                {presets.map((p) => {
                  const { Icon } = presetVisual(p.id, p.label)
                  const on = activePreset === p.id
                  return (
                    <button
                      key={p.id}
                      onClick={() => applyPreset(p)}
                      className={`inline-flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-2 text-[13px] font-medium transition ${
                        on ? 'border-ink-900 bg-ink-900 text-white' : 'border-ink-200 text-ink-800 hover:border-ink-400'
                      }`}
                    >
                      <Icon className={`h-4 w-4 ${on ? 'text-sun-500' : 'text-teal-600'}`} strokeWidth={1.8} />
                      {p.label}
                    </button>
                  )
                })}
              </ScrollStrip>
            ))}

          {/* Результаты */}
          <div ref={resultsRef} className="scroll-mt-20 space-y-8">
            {inResults && (
              <button
                type="button"
                onClick={goBack}
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-200 px-4 text-[14px] font-semibold text-ink-900 transition hover:border-ink-900"
                title="Esc"
              >
                <ArrowLeft className="h-4 w-4" strokeWidth={2} />
                {t.back}
              </button>
            )}
            {loading && <Skeleton text={t.loading} />}

            {!loading && error && (
              <div className="rounded-2xl border border-closed/30 p-5">
                <p className="font-display text-[18px] font-semibold text-ink-900">{t.errorTitle}</p>
                <p className="mt-1 text-[15px] text-ink-600">
                  {error.message} <span className="text-ink-400">({error.code})</span>
                </p>
                <button
                  onClick={() => lastReq.current && run(lastReq.current.req, lastReq.current.presetId)}
                  className="mt-3 rounded-full bg-ink-900 px-5 py-2 text-[14px] font-semibold text-white hover:bg-ink-800"
                >
                  {t.retry}
                </button>
              </div>
            )}

            {!loading && !error && shown && (
              <>
                <Results
                  result={shown.res}
                  query={shown.req.query}
                  start={shown.req.location}
                  t={t}
                  lang={lang}
                  mode={shown.req.mode}
                  onWiden={widen}
                  hovered={hovered}
                  onHover={setHovered}
                  focusIndex={focusIndex}
                  photos={photos}
                />
                <ContextUsed result={shown.res} t={t} />
              </>
            )}
          </div>

          <p className="border-t border-ink-100 pt-4 text-[12px] leading-relaxed text-ink-400">{t.credits}</p>
        </div>
      </aside>
    </div>
  )
}

function Hero({ hero, t }: { hero: import('./types').ImageRef | null; t: Dict }) {
  return (
    <figure className="rise">
      <div className="relative h-[230px] overflow-hidden rounded-3xl bg-[#0b2545] sm:h-[300px]">
        {hero && (
          <img
            src={imgSrc(hero)}
            alt={t.heroAlt}
            referrerPolicy="no-referrer"
            className="absolute inset-0 h-full w-full object-cover"
            onError={(e) => ((e.currentTarget as HTMLImageElement).style.display = 'none')}
          />
        )}
        {/* затемнение снизу — только чтобы заголовок читался на фото */}
        <div className="absolute inset-0 bg-[linear-gradient(to_top,rgb(6_24_47/0.78),rgb(6_24_47/0.1)_60%,transparent)]" />
        <div className="absolute inset-x-0 bottom-0 p-5 sm:p-6">
          <h1 className="max-w-[18ch] font-display text-[26px] font-semibold leading-[1.15] text-[#fff] sm:text-[32px]">{t.heroTitle}</h1>
          <p className="mt-2 max-w-[42ch] text-[15px] leading-snug text-[#ffffffd9]">{t.heroSub}</p>
        </div>
      </div>
      {hero && <Credit img={hero} t={t} />}
    </figure>
  )
}

/** Что уйдёт на сервер: режим, время, фильтры — всегда на виду под полем запроса. */
function SendSummary({
  t,
  c,
  budget,
  fromPreset,
  onClearBudget,
}: {
  t: Dict
  c: ControlsState
  budget: number | null
  fromPreset: boolean
  onClearBudget: () => void
}) {
  const time = c.presetTime ? isoClock(c.presetTime) : `${t[`slot_${c.slot}` as const]}, ${isoClock(slotToIso(c.slot))}`
  const parts = [
    c.mode === 'car' ? t.car : t.walk,
    time,
    c.withKids ? t.withKids : null,
    c.accessibility ? t.accessibility : null,
    c.groupSize > 1 ? `${t.group} ${c.groupSize}` : null,
    c.indoorOnly ? t.indoorOnly : null,
    c.weather ? `${t.winter} ${c.weather.temp_c}°` : null,
  ].filter(Boolean)
  return (
    <p className="min-w-0 text-[13px] text-ink-500">
      {parts.join(' · ')}
      {budget != null && (
        <>
          {' · '}
          {budget >= 60 && budget % 60 === 0 ? `${budget / 60} ${t.hourShort}` : `${budget} ${t.min}`}
          {!fromPreset && (
            <button type="button" onClick={onClearBudget} className="ml-0.5 inline-flex align-middle text-ink-400 hover:text-ink-800" aria-label="×">
              <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
          )}
        </>
      )}
      {fromPreset && <span className="ml-1.5 text-teal-700">· {t.fromPreset}</span>}
    </p>
  )
}

function Skeleton({ text }: { text: string }) {
  return (
    <div className="space-y-8" aria-busy>
      <p className="flex items-center gap-2 text-[15px] text-ink-600">
        <LoaderCircle className="h-4 w-4 animate-spin text-teal-600" strokeWidth={2} />
        {text}
      </p>
      {[0, 1].map((i) => (
        <div key={i} className="space-y-3">
          <div className="skeleton aspect-[16/9] rounded-2xl" />
          <div className="skeleton h-3 w-24 rounded" />
          <div className="skeleton h-6 w-2/3 rounded" />
          <div className="skeleton h-4 w-full rounded" />
          <div className="skeleton h-4 w-5/6 rounded" />
        </div>
      ))}
    </div>
  )
}
