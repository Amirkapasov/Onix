import { forwardRef } from 'react'
import type { Lang, OpenStatus, Recommendation } from '../types'
import { BADGE_LABELS, CATEGORY_ICONS, CATEGORY_LABELS, type Dict } from '../i18n'
import { formatDistance } from '../geo'

const SOURCE_NAMES: Record<string, string> = {
  osm: 'OSM',
  wikidata: 'Wikidata',
  wikipedia: 'Wikipedia',
  '2gis': '2GIS',
  official_site: 'сайт',
  seed: 'ручная база',
  manual: 'ручная база',
}

export function StatusBadge({ s, t }: { s: OpenStatus; t: Dict }) {
  let cls = 'bg-slate-100 text-slate-700 ring-slate-300'
  let dot = 'bg-slate-400'
  let text = t.status_unknown
  if (s.state === 'open' && s.confidence === 'high') {
    cls = 'bg-emerald-50 text-emerald-800 ring-emerald-300'
    dot = 'bg-emerald-500'
    text = t.status_open_high
  } else if (s.state === 'open') {
    cls = 'bg-amber-50 text-amber-900 ring-amber-300'
    dot = 'bg-amber-400'
    text = s.confidence === 'medium' ? t.status_open_medium : t.status_open_low
  } else if (s.state === 'closed') {
    cls = 'bg-rose-50 text-rose-800 ring-rose-300'
    dot = 'bg-rose-500'
    text = t.status_closed
  }
  return (
    <span
      title={s.label}
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold ring-1 ${cls}`}
    >
      <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
      {text}
    </span>
  )
}

export function SourceBadge({ r, t }: { r: Recommendation; t: Dict }) {
  const src = r.sources ?? []
  const names = [...new Set(src.map((s) => SOURCE_NAMES[s.name] ?? s.name))].join(' / ')
  const url = src.find((s) => s.url)?.url
  const content = (
    <>
      📍 {t.fromDb}
      {names && <span className="font-normal text-sky-700/80">· {names}</span>}
      {url && <span aria-hidden>↗</span>}
    </>
  )
  const cls =
    'inline-flex items-center gap-1.5 rounded-full bg-sky-50 px-3 py-1 text-sm font-semibold text-sky-800 ring-1 ring-sky-200'
  return url ? (
    <a href={url} target="_blank" rel="noreferrer" className={`${cls} hover:bg-sky-100`} onClick={(e) => e.stopPropagation()}>
      {content}
    </a>
  ) : (
    <span className={cls}>{content}</span>
  )
}

// Выделяем значимые для решения теги: круглосуточно и «недорого» (это эвристика — подписано как оценка).
const BADGE_STYLE: Record<string, string> = {
  '24_7': 'bg-emerald-100 font-bold text-emerald-800',
  budget: 'bg-amber-100 text-amber-900',
}

function badgeText(b: string, lang: Lang): string {
  if (b.startsWith('brand:')) return b.slice(6)
  return BADGE_LABELS[b]?.[lang] ?? b
}

interface Props {
  r: Recommendation
  index: number
  t: Dict
  lang: Lang
  mode: string
  active: boolean
  onHover: (i: number | null) => void
}

const RecommendationCard = forwardRef<HTMLElement, Props>(function RecommendationCard(
  { r, index, t, lang, mode, active, onHover },
  ref,
) {
  const visit = r.visit_min && r.visit_min.length ? r.visit_min : null
  const visitText = visit ? (visit.length > 1 && visit[0] !== visit[1] ? `${visit[0]}–${visit[1]}` : `${visit[0]}`) : null
  const cat = CATEGORY_LABELS[r.category]?.[lang] ?? r.category
  const icon = CATEGORY_ICONS[r.category] ?? '📍'

  return (
    <article
      ref={ref}
      onMouseEnter={() => onHover(index)}
      onMouseLeave={() => onHover(null)}
      className={`card-in rounded-3xl bg-white p-5 shadow-sm ring-2 transition sm:p-6 ${
        active ? 'shadow-lg ring-amber-400' : 'ring-slate-200/70'
      }`}
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <header className="flex items-start gap-4">
        <div
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl text-xl font-extrabold ${
            active ? 'bg-amber-400 text-slate-900' : 'bg-sky-600 text-white'
          }`}
        >
          {index + 1}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-xl font-extrabold leading-tight text-slate-900 sm:text-2xl">{r.name}</h3>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px] text-slate-600">
            <span>
              {icon} {cat}
            </span>
            <span className="font-semibold text-slate-800">
              {mode === 'car' ? '🚗' : '🚶'} {formatDistance(r.distance_m, lang)} · {r.travel_min} {t.min}
            </span>
            {visitText && (
              <span>
                ⏱ {t.onVisit} {visitText} {t.min}
              </span>
            )}
            {r.rating != null && <span>★ {r.rating.toFixed(1)}</span>}
          </div>
        </div>
      </header>

      <div className="mt-4 flex flex-wrap gap-2">
        <StatusBadge s={r.open_status} t={t} />
        <SourceBadge r={r} t={t} />
      </div>
      {r.open_status.label && r.open_status.state !== 'unknown' && <p className="mt-1.5 text-[13px] text-slate-500">{r.open_status.label}</p>}

      <dl className="mt-4 space-y-3 text-[17px] leading-snug">
        <div>
          <dt className="text-xs font-bold uppercase tracking-wider text-sky-700">{t.why}</dt>
          <dd className="mt-0.5 text-slate-800">{r.why}</dd>
        </div>
        <div className="rounded-2xl bg-amber-50 px-4 py-3">
          <dt className="text-xs font-bold uppercase tracking-wider text-amber-700">{t.whatToDo}</dt>
          <dd className="mt-0.5 text-slate-800">{r.what_to_do}</dd>
        </div>
      </dl>

      {r.badges && r.badges.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {r.badges.map((b) => (
            <span key={b} className={`rounded-full px-2.5 py-0.5 text-[13px] font-medium ${BADGE_STYLE[b] ?? 'bg-slate-100 text-slate-600'}`}>
              {badgeText(b, lang)}
            </span>
          ))}
        </div>
      )}
    </article>
  )
})

export default RecommendationCard
