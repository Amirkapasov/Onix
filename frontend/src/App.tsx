import { useCallback, useEffect, useRef, useState } from 'react'
import MapView from './components/MapView'
import Controls, { type ControlsState } from './components/Controls'
import Results from './components/Results'
import ContextUsed from './components/ContextUsed'
import { ApiError, USE_MOCK, fetchHealth, fetchPois, fetchPresets, recommend } from './api'
import { coarsen, slotToIso } from './geo'
import { DICTS, presetIcon } from './i18n'
import type { Lang, LatLon, Poi, Preset, RecommendRequest, RecommendResponse } from './types'

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
  const [controls, setControls] = useState<ControlsState>(DEFAULT_CONTROLS)
  const [timeBudget, setTimeBudget] = useState<number | null>(null)
  const [presets, setPresets] = useState<Preset[]>([])
  const [activePreset, setActivePreset] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>([])

  const [result, setResult] = useState<RecommendResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const [focusIndex, setFocusIndex] = useState<number | null>(null)
  const [backendUp, setBackendUp] = useState<boolean | null>(null)
  const [pois, setPois] = useState<Poi[]>([])
  const [geoAsk, setGeoAsk] = useState(false)
  const [geoErr, setGeoErr] = useState(false)

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
    if (!USE_MOCK) {
      fetchHealth().then(setBackendUp)
      fetchPois([51.0, 71.3, 51.22, 71.6])
        .then((items) => setPois(items.slice(0, 1500)))
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
      if (seq !== reqSeq.current) return
      setResult(res)
      if (!STATIC || window.innerWidth >= 1024)
        requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: STATIC ? 'instant' : 'smooth', block: 'start' }))
    } catch (e) {
      if (seq !== reqSeq.current) return
      setResult(null)
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
    location_label: labelText(label),
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

  const submit = (q = query) => {
    const text = q.trim()
    if (!text || loading) return
    setQuery(text)
    run(buildRequest(text, location, locationLabel, controls, timeBudget), activePreset ?? undefined)
  }

  const applyPreset = (p: Preset) => {
    const f = p.filters ?? {}
    const c: ControlsState = {
      ...controls,
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
    setControls(c)
    setLocation(loc)
    setLocationLabel(label)
    setQuery(p.query)
    setTimeBudget(budget)
    setActivePreset(p.id)
    run(buildRequest(p.query, loc, label, c, budget, f.categories ?? []), p.id)
  }

  // Спец-метки переводятся при показе, чтобы смена языка их подхватывала.
  const PICKED = '__picked__'
  const GEO = '__geo__'
  const labelText = (l: string) => (l === PICKED ? t.pickedPoint : l === GEO ? t.myLocation : l)

  const pickLocation = (p: LatLon, label = PICKED) => {
    setLocation(coarsen(p))
    setLocationLabel(label)
    setActivePreset(null)
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

  const shownLoc = coarsen(location)

  return (
    <div className="flex min-h-dvh flex-col bg-slate-50 lg:h-dvh">
      {/* Шапка */}
      <header className="z-10 flex items-center justify-between gap-3 bg-gradient-to-r from-sky-700 via-sky-600 to-sky-500 px-4 py-3 text-white shadow-md sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-amber-400 text-2xl shadow-inner">
            ☀️
          </div>
          <div className="min-w-0">
            <h1 className="text-2xl font-black leading-none tracking-tight">Серуен</h1>
            <p className="truncate text-sm font-medium text-sky-100">{t.tagline}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span
            className={`hidden rounded-full px-3 py-1 text-xs font-bold sm:inline-block ${
              USE_MOCK ? 'bg-white/20' : backendUp === false ? 'bg-rose-500' : 'bg-emerald-500'
            }`}
          >
            {USE_MOCK ? t.mockBadge : `● ${t.liveBadge}`}
          </span>
          <div className="flex rounded-full bg-white/15 p-0.5" role="group" aria-label="Language">
            {LANGS.map((l) => (
              <button
                key={l.id}
                onClick={() => setLang(l.id)}
                aria-pressed={lang === l.id}
                className={`rounded-full px-2.5 py-1 text-sm font-bold transition sm:px-3 ${
                  lang === l.id ? 'bg-white text-sky-700' : 'text-white hover:bg-white/10'
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="flex flex-1 flex-col lg:min-h-0 lg:flex-row">
        {/* Карта */}
        <section className="relative h-[46vh] max-h-[480px] min-h-[300px] lg:h-auto lg:max-h-none lg:flex-1">
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
          />
        </section>

        {/* Панель */}
        <aside className="w-full lg:w-[480px] lg:shrink-0 lg:overflow-y-auto xl:w-[600px]">
          <div className="space-y-5 p-4 sm:p-6">
            {/* Локация */}
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
              <div className="min-w-0">
                <p className="truncate text-[17px] font-bold text-slate-900">📍 {labelText(locationLabel)}</p>
                <p className="text-[13px] text-slate-500">
                  ≈ {shownLoc.lat.toFixed(3)}, {shownLoc.lon.toFixed(3)} · {t.locationCoarse}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setGeoAsk(true)}
                className="rounded-full border-2 border-sky-200 px-3 py-1.5 text-sm font-semibold text-sky-700 hover:bg-sky-50"
              >
                🎯 {t.myLocation}
              </button>
              {geoAsk && (
                <div className="w-full rounded-xl bg-sky-50 p-3 text-[14px] text-slate-700">
                  <p className="font-bold text-slate-900">{t.geoConsentTitle}</p>
                  <p className="mt-1">{t.geoConsentText}</p>
                  <div className="mt-2 flex gap-2">
                    <button onClick={askGeo} className="rounded-full bg-sky-600 px-4 py-1.5 font-semibold text-white">
                      {t.allow}
                    </button>
                    <button onClick={() => setGeoAsk(false)} className="rounded-full px-4 py-1.5 font-semibold text-slate-600 hover:bg-white">
                      {t.cancel}
                    </button>
                  </div>
                </div>
              )}
              {geoErr && <p className="w-full text-[14px] text-rose-700">{t.geoError}</p>}
            </div>

            {/* Запрос */}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                submit()
              }}
              className="rounded-3xl bg-white p-2 shadow-md ring-2 ring-sky-100 focus-within:ring-sky-400"
            >
              <textarea
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value)
                  setActivePreset(null)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                rows={2}
                placeholder={t.queryPlaceholder}
                className="w-full resize-none rounded-2xl px-3 py-2 text-[18px] leading-snug text-slate-900 outline-none placeholder:text-slate-400"
              />
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={!query.trim() || loading}
                  className="rounded-2xl bg-amber-400 px-6 py-3 text-[17px] font-extrabold text-slate-900 shadow-sm transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {loading ? '…' : `${t.send} →`}
                </button>
              </div>
            </form>

            {history.length > 0 && (
              <div className="-mt-2 flex flex-wrap items-center gap-1.5">
                <span className="text-[13px] font-semibold text-slate-400">{t.history}:</span>
                {history.map((h) => (
                  <button
                    key={h}
                    onClick={() => submit(h)}
                    className="max-w-[260px] truncate rounded-full bg-slate-200/70 px-3 py-1 text-[13px] text-slate-700 hover:bg-slate-200"
                    title={h}
                  >
                    ↺ {h}
                  </button>
                ))}
              </div>
            )}

            {/* Пресеты */}
            {presets.length > 0 && (
              <div>
                <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-slate-500">⚡ {t.presets}</h2>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {presets.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => applyPreset(p)}
                      disabled={loading}
                      className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-left text-[16px] font-bold leading-tight shadow-sm ring-2 transition disabled:opacity-60 ${
                        activePreset === p.id
                          ? 'bg-sky-600 text-white ring-sky-600'
                          : 'bg-white text-slate-800 ring-slate-200 hover:-translate-y-0.5 hover:ring-sky-400'
                      }`}
                    >
                      <span className="text-3xl">{p.icon ?? presetIcon(p.id, p.label)}</span>
                      <span>{p.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <Controls t={t} value={controls} onChange={setControls} slotIso={slotToIso} />

            {/* Результаты */}
            <div ref={resultsRef} className="scroll-mt-4 space-y-4">
              {loading && <Skeleton text={t.loading} />}

              {!loading && error && (
                <div className="rounded-3xl border-2 border-rose-200 bg-rose-50 p-5">
                  <p className="text-lg font-extrabold text-rose-900">😕 {t.errorTitle}</p>
                  <p className="mt-1 text-[15px] text-rose-800">
                    {error.message} <span className="text-rose-500">({error.code})</span>
                  </p>
                  <button
                    onClick={() => lastReq.current && run(lastReq.current.req, lastReq.current.presetId)}
                    className="mt-3 rounded-full bg-rose-600 px-5 py-2 font-bold text-white hover:bg-rose-500"
                  >
                    {t.retry}
                  </button>
                </div>
              )}

              {!loading && !error && result && (
                <>
                  <Results
                    result={result}
                    t={t}
                    lang={lang}
                    mode={lastReq.current?.req.mode ?? 'walk'}
                    hovered={hovered}
                    onHover={setHovered}
                    focusIndex={focusIndex}
                  />
                  <ContextUsed result={result} t={t} />
                </>
              )}

              {!loading && !error && !result && (
                <div className="rounded-3xl border-2 border-dashed border-sky-200 bg-sky-50/60 p-6 text-center">
                  <p className="text-4xl">🧭</p>
                  <p className="mt-2 text-xl font-extrabold text-slate-900">{t.emptyTitle}</p>
                  <p className="mx-auto mt-1 max-w-md text-[16px] text-slate-600">{t.emptyText}</p>
                </div>
              )}
            </div>

            <p className="pb-2 text-center text-[12px] text-slate-400">
              Серуен · OpenStreetMap, Wikidata, 2GIS · {USE_MOCK ? 'mock' : 'api'}
            </p>
          </div>
        </aside>
      </main>
    </div>
  )
}

function Skeleton({ text }: { text: string }) {
  return (
    <div className="space-y-4" aria-busy>
      <p className="flex items-center gap-2 text-[16px] font-semibold text-sky-700">
        <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
        {text}
      </p>
      {[0, 1, 2].map((i) => (
        <div key={i} className="animate-pulse rounded-3xl bg-white p-6 ring-1 ring-slate-200">
          <div className="flex gap-4">
            <div className="h-11 w-11 rounded-2xl bg-slate-200" />
            <div className="flex-1 space-y-2">
              <div className="h-5 w-2/3 rounded bg-slate-200" />
              <div className="h-4 w-1/2 rounded bg-slate-100" />
            </div>
          </div>
          <div className="mt-4 h-4 w-full rounded bg-slate-100" />
          <div className="mt-2 h-4 w-5/6 rounded bg-slate-100" />
        </div>
      ))}
    </div>
  )
}
