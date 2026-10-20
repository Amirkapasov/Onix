import { useEffect, useRef } from 'react'
import { Car, Clock, Info, Lightbulb, MapPin, SearchX, Thermometer, TriangleAlert } from 'lucide-react'
import type { CategoryPhotos, Lang, RecommendResponse } from '../types'
import type { Dict } from '../i18n'
import { formatDistance } from '../geo'
import { assignIllustrations } from '../photos'
import RecommendationCard from './RecommendationCard'

interface Props {
  result: RecommendResponse
  query: string
  onWiden: (kind: 'budget' | 'car') => void
  t: Dict
  lang: Lang
  mode: string
  hovered: number | null
  onHover: (i: number | null) => void
  focusIndex: number | null
  photos: CategoryPhotos
}

const LLM_WARNING = /ИИ-модель|ЖИ модел|AI model|LLM/i
const DEGRADED_PROVIDERS = ['none', 'fallback', 'template', 'ranking', 'degraded', 'off']

export function isDegraded(r: RecommendResponse): boolean {
  const flag = (r as unknown as { degraded?: boolean }).degraded
  if (flag) return true
  if (r.llm === null) return true
  const p = r.llm?.provider?.toLowerCase()
  return !!p && DEGRADED_PROVIDERS.includes(p)
}

export default function Results({ result, query, onWiden, t, lang, mode, hovered, onHover, focusIndex, photos }: Props) {
  const refs = useRef<(HTMLElement | null)[]>([])
  const recs = result.recommendations ?? []
  const ideas = result.ideas ?? []
  const degraded = isDegraded(result)
  // Предупреждение «ИИ-модель недоступна» показываем тихой строкой, а не в блоке предупреждений.
  const warnings = (result.warnings ?? []).filter((w) => !(degraded && LLM_WARNING.test(w)))
  const route = result.route
  const ctx = result.context_used

  useEffect(() => {
    if (focusIndex != null) refs.current[focusIndex]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [focusIndex])

  const nameOf = (id: string) => {
    const i = recs.findIndex((r) => r.poi_id === id)
    return i >= 0 ? { n: i + 1, name: recs[i].name } : { n: null, name: id }
  }
  const routeM = route?.legs?.reduce((s, l) => s + (l.distance_m || 0), 0) ?? 0
  const illustrations = assignIllustrations(recs, photos.categories)
  const simulated = /симуляц|simulat/i.test(ctx?.weather ?? '')

  return (
    <div className="space-y-6">
      <header>
        <p className="truncate text-[14px] text-ink-500" title={query}>
          {t.forQuery} <span className="text-ink-800">«{query}»</span>
        </p>
        {recs.length > 0 && (
          <h2 className="mt-1 font-display text-[26px] font-semibold leading-tight text-ink-900">{t.resultsTitle(recs.length)}</h2>
        )}
        {ctx && (
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[14px] text-ink-500">
            {ctx.location && (
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="h-4 w-4 text-ink-400" strokeWidth={1.8} />
                {ctx.location}
              </span>
            )}
            {ctx.time && (
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-4 w-4 text-ink-400" strokeWidth={1.8} />
                {ctx.time}
              </span>
            )}
            {ctx.weather && (
              <span className={`inline-flex items-center gap-1.5 ${simulated ? 'text-teal-700' : ''}`}>
                <Thermometer className="h-4 w-4 text-ink-400" strokeWidth={1.8} />
                {ctx.weather}
              </span>
            )}
          </p>
        )}
        {degraded && (
          <p className="mt-2 flex items-start gap-1.5 text-[13px] text-ink-500">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-400" strokeWidth={2} />
            <span>
              <span className="font-semibold text-ink-700">{t.degradedTag}.</span> {t.degraded}
            </span>
          </p>
        )}
      </header>

      {warnings.length > 0 && (
        <div className="space-y-1.5 border-l-[3px] border-sun-500 py-0.5 pl-4">
          {warnings.map((w, i) => (
            <p key={i} className="flex gap-2 text-[15px] leading-snug text-ink-800">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-sun-600" strokeWidth={2} />
              <span>{w}</span>
            </p>
          ))}
        </div>
      )}

      {recs.length <= 1 && (
        <section className="rounded-2xl bg-ink-50 p-5">
          <div className="flex items-start gap-3">
            <SearchX className="mt-1 h-6 w-6 shrink-0 text-ink-400" strokeWidth={1.6} />
            <div>
              <p className="font-display text-[18px] font-semibold text-ink-900">{recs.length === 0 ? t.nothingTitle : t.fewTitle}</p>
              <p className="mt-1 text-[15px] leading-snug text-ink-600">{recs.length === 0 ? t.nothingText : t.fewText}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => onWiden('budget')}
                  className="inline-flex items-center gap-2 rounded-full bg-ink-900 px-4 py-2 text-[14px] font-semibold text-white hover:bg-ink-800"
                >
                  <Clock className="h-4 w-4" strokeWidth={2} />
                  {t.widenBudget}
                </button>
                {mode !== 'car' && (
                  <button
                    type="button"
                    onClick={() => onWiden('car')}
                    className="inline-flex items-center gap-2 rounded-full border border-ink-200 bg-white px-4 py-2 text-[14px] font-semibold text-ink-900 hover:border-ink-400"
                  >
                    <Car className="h-4 w-4" strokeWidth={2} />
                    {t.widenCar}
                  </button>
                )}
              </div>
            </div>
          </div>
        </section>
      )}

      <div className="space-y-10">
        {recs.map((r, i) => (
          <RecommendationCard
            key={r.poi_id}
            ref={(el) => {
              refs.current[i] = el
            }}
            r={r}
            index={i}
            t={t}
            lang={lang}
            mode={mode}
            active={hovered === i}
            illustration={illustrations[i]}
            onHover={onHover}
          />
        ))}
      </div>

      {route && route.stops?.length > 1 && (
        <section className="border-t border-ink-100 pt-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-display text-[18px] font-semibold text-ink-900">{t.route}</h3>
            <p className="text-[15px] font-semibold text-ink-700">
              {t.places(route.stops.length)} · {route.total_min} {t.min}
              {routeM > 0 && ` · ${formatDistance(routeM, lang)}`}
            </p>
          </div>
          <ol className="relative mt-4 space-y-4 pl-9">
            <span className="absolute bottom-3 left-[13px] top-3 w-0.5 bg-teal-100" aria-hidden />
            <li className="relative text-[15px] text-ink-500">
              <span className="absolute -left-9 top-0.5 flex h-7 w-7 items-center justify-center rounded-full border-2 border-teal-500 bg-white">
                <span className="h-2 w-2 rounded-full bg-teal-500" />
              </span>
              {t.start}
            </li>
            {(route.legs ?? []).map((leg, i) => {
              const to = nameOf(leg.to)
              return (
                <li key={i} className="relative">
                  <span className="absolute -left-9 top-0 flex h-7 w-7 items-center justify-center rounded-full bg-ink-900 text-[13px] font-bold text-white">
                    {to.n ?? '•'}
                  </span>
                  <p className="text-[16px] font-semibold leading-snug text-ink-900">{to.name}</p>
                  <p className="text-[13px] text-ink-500">
                    + {formatDistance(leg.distance_m, lang)} · {leg.minutes} {t.min}
                  </p>
                </li>
              )
            })}
          </ol>
        </section>
      )}

      {ideas.length > 0 && (
        <section className="border-t border-ink-100 pt-6">
          <div className="flex items-center gap-2">
            <Lightbulb className="h-5 w-5 text-sun-600" strokeWidth={1.8} />
            <h3 className="font-display text-[16px] font-semibold text-ink-900">{t.aiIdea}</h3>
          </div>
          <p className="mt-0.5 text-[13px] text-ink-400">{t.aiIdeaHint}</p>
          <ul className="mt-3 space-y-2">
            {ideas.map((idea, i) => (
              <li key={i} className="text-[16px] leading-relaxed text-ink-800">
                {idea.text}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
