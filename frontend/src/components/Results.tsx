import { useEffect, useRef } from 'react'
import type { Lang, RecommendResponse } from '../types'
import type { Dict } from '../i18n'
import { formatDistance } from '../geo'
import RecommendationCard from './RecommendationCard'

interface Props {
  result: RecommendResponse
  t: Dict
  lang: Lang
  mode: string
  hovered: number | null
  onHover: (i: number | null) => void
  focusIndex: number | null
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

export default function Results({ result, t, lang, mode, hovered, onHover, focusIndex }: Props) {
  const refs = useRef<(HTMLElement | null)[]>([])
  const recs = result.recommendations ?? []
  const ideas = result.ideas ?? []
  const degraded = isDegraded(result)
  // Предупреждение «ИИ-модель недоступна» показываем мягкой плашкой, а не в жёлтом блоке.
  const warnings = (result.warnings ?? []).filter((w) => !(degraded && LLM_WARNING.test(w)))
  const route = result.route

  useEffect(() => {
    if (focusIndex != null) refs.current[focusIndex]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focusIndex])

  const nameOf = (id: string) => {
    const i = recs.findIndex((r) => r.poi_id === id)
    return i >= 0 ? { n: i + 1, name: recs[i].name } : { n: null, name: id }
  }
  const routeKm = route?.legs?.reduce((s, l) => s + (l.distance_m || 0), 0) ?? 0

  return (
    <div className="space-y-4">
      {recs.length > 0 && (
        <h2 className="flex items-center gap-2 text-2xl font-black text-slate-900">
          <span className="h-7 w-1.5 rounded-full bg-amber-400" />
          {t.resultsTitle(recs.length)}
        </h2>
      )}
      {result.context_used && (
        <div className="flex flex-wrap gap-1.5 text-[13px] font-medium text-slate-600">
          {[
            result.context_used.location && `📍 ${result.context_used.location}`,
            result.context_used.time && `🕒 ${result.context_used.time}`,
            result.context_used.weather &&
              `${/симуляц|simulat/i.test(result.context_used.weather) ? '❄️' : '🌡️'} ${result.context_used.weather}`,
            ...(result.context_used.filters ?? []).slice(0, 2).map((f) => `✓ ${f}`),
            (result.context_used.filters?.length ?? 0) > 2 && `+${result.context_used.filters!.length - 2} ↓`,
          ]
            .filter(Boolean)
            .map((s) => (
              <span key={s as string} className="rounded-full bg-white px-2.5 py-1 ring-1 ring-slate-200">
                {s}
              </span>
            ))}
        </div>
      )}
      {degraded && (
        <div className="flex items-start gap-3 rounded-2xl bg-sky-50 px-4 py-3 ring-1 ring-sky-200">
          <span className="mt-0.5 shrink-0 whitespace-nowrap rounded-full bg-sky-600 px-2 py-0.5 text-[12px] font-bold uppercase tracking-wide text-white">
            {t.degradedTag}
          </span>
          <p className="text-[15px] leading-snug text-sky-950">{t.degraded}</p>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="rounded-2xl border-2 border-amber-300 bg-amber-50 px-4 py-3">
          {warnings.map((w, i) => (
            <p key={i} className="flex gap-2 text-[16px] font-medium text-amber-950">
              <span aria-hidden>⚠️</span>
              <span>{w}</span>
            </p>
          ))}
        </div>
      )}

      {recs.length === 0 && (
        <div className="rounded-2xl bg-white p-5 text-[17px] text-slate-700 ring-1 ring-slate-200">{t.noResults}</div>
      )}

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
          onHover={onHover}
        />
      ))}

      {route && route.stops?.length > 0 && (
        <section className="rounded-3xl bg-gradient-to-br from-sky-600 to-sky-800 p-5 text-white shadow-md">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-lg font-extrabold">🗺️ {t.route}</h3>
            <p className="text-lg font-bold tabular-nums">
              {t.places(route.stops.length)} · {route.total_min} {t.min}
              {routeKm > 0 && ` · ${formatDistance(routeKm, lang)}`}
            </p>
          </div>
          <ol className="mt-3 space-y-2 text-[15px]">
            {(route.legs ?? []).map((leg, i) => {
              const to = nameOf(leg.to)
              return (
                <li key={i} className="flex items-center gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-400 text-sm font-extrabold text-slate-900">
                    {to.n ?? '•'}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-semibold">{to.name}</span>
                  <span className="shrink-0 tabular-nums text-sky-100">
                    {i === 0 ? `${t.start} → ` : '→ '}
                    {formatDistance(leg.distance_m, lang)} · {leg.minutes} {t.min}
                  </span>
                </li>
              )
            })}
          </ol>
        </section>
      )}

      {ideas.length > 0 && (
        <section className="rounded-3xl border-2 border-dashed border-violet-300 bg-violet-50/60 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-violet-600 px-3 py-1 text-sm font-bold text-white">💡 {t.aiIdea}</span>
            <span className="text-[13px] text-violet-700">{t.aiIdeaHint}</span>
          </div>
          <ul className="mt-3 space-y-2">
            {ideas.map((idea, i) => (
              <li key={i} className="text-[16px] leading-snug text-slate-800">
                {idea.text}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
