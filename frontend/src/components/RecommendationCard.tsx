import { forwardRef } from 'react'
import { Car, Clock, Database, Footprints, Star } from 'lucide-react'
import type { ImageRef, Lang, OpenStatus, Recommendation } from '../types'
import { BADGE_LABELS, CATEGORY_LABELS, type Dict } from '../i18n'
import { formatDistance } from '../geo'
import Photo from './Photo'
import NavButtons from './NavButtons'

const SOURCE_NAMES: Record<string, string> = {
  osm: 'OpenStreetMap',
  wikidata: 'Wikidata',
  wikipedia: 'Wikipedia',
  '2gis': '2GIS',
  official_site: 'сайт',
  seed: 'ручная база',
  manual: 'ручная база',
}

/** Статус работы: цветная точка + текст + уверенность. Без «светофорных» плашек. */
export function OpenStatusLine({ s, t }: { s: OpenStatus; t: Dict }) {
  let dot = 'bg-ink-300'
  let text = t.st_unknown
  if (s.state === 'open' && s.confidence === 'high') {
    dot = 'bg-open'
    text = t.st_open
  } else if (s.state === 'open') {
    dot = 'bg-maybe'
    text = s.confidence === 'medium' ? t.st_probably : t.st_possibly
  } else if (s.state === 'closed') {
    dot = 'bg-closed'
    text = t.st_closed
  }
  const conf = s.state === 'unknown' ? null : t[`conf_${s.confidence}` as const]
  return (
    <span className="inline-flex items-center gap-2" title={s.label}>
      <span className="relative flex h-2.5 w-2.5">
        {s.state === 'open' && s.confidence === 'high' && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-open opacity-40 motion-reduce:hidden" />
        )}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dot}`} />
      </span>
      <span className="font-semibold text-ink-900">{text}</span>
      {conf && <span className="text-ink-400">· {conf}</span>}
    </span>
  )
}

function badgeText(b: string, lang: Lang): string {
  if (b.startsWith('brand:')) return b.slice(6)
  return BADGE_LABELS[b]?.[lang] ?? b.replace(/_/g, ' ')
}
// Показываем только теги, полезные для решения; остальное — шум.
const KEY_BADGES = new Set(['24_7', 'budget', 'free', 'indoor', 'outdoor', 'kids', 'wheelchair', 'quiet', 'view', 'night'])

interface Props {
  r: Recommendation
  index: number
  t: Dict
  lang: Lang
  mode: string
  active: boolean
  illustration: ImageRef | null
  navLinks: { id: string; label: string; url: string }[]
  onHover: (i: number | null) => void
}

const RecommendationCard = forwardRef<HTMLElement, Props>(function RecommendationCard(
  { r, index, t, lang, mode, active, illustration, navLinks, onHover },
  ref,
) {
  const visit = r.visit_min && r.visit_min.length ? r.visit_min : null
  const visitText = visit ? (visit.length > 1 && visit[0] !== visit[1] ? `${visit[0]}–${visit[1]}` : `${visit[0]}`) : null
  const cat = CATEGORY_LABELS[r.category]?.[lang] ?? r.category
  const src = r.sources ?? []
  const srcNames = [...new Set(src.map((s) => SOURCE_NAMES[s.name] ?? s.name))].join(', ')
  const srcUrl = src.find((s) => s.url)?.url
  const badges = (r.badges ?? []).filter((b) => KEY_BADGES.has(b) || b.startsWith('brand:')).slice(0, 4)
  const Move = mode === 'car' ? Car : Footprints

  return (
    <article
      ref={ref}
      onMouseEnter={() => onHover(index)}
      onMouseLeave={() => onHover(null)}
      className="rise scroll-mt-24"
      style={{ animationDelay: `${index * 90}ms` }}
    >
      <Photo
        image={r.image}
        illustration={illustration}
        category={r.category}
        alt={r.name}
        t={t}
        className={`aspect-[16/9] rounded-2xl transition duration-300 ${active ? 'ring-4 ring-sun-500' : ''}`}
      >
        <span
          className={`absolute left-3 top-3 flex h-9 w-9 items-center justify-center rounded-full text-[15px] font-bold shadow-sm transition ${
            active ? 'bg-sun-500 text-[#0b2545]' : 'bg-white text-ink-900'
          }`}
        >
          {index + 1}
        </span>
      </Photo>

      <div className="mt-3">
        <p className="text-[13px] font-semibold uppercase tracking-[0.08em] text-teal-600">{cat}</p>
        <h3 className="mt-1 font-display text-[22px] font-semibold leading-[1.2] text-ink-900 sm:text-2xl">{r.name}</h3>
        <p className="mt-2.5 text-[17px] leading-relaxed text-ink-800">{r.why}</p>

        <div className="mt-3 border-l-[3px] border-sun-500 pl-4">
          <p className="text-[13px] font-semibold text-ink-500">{t.whatToDo}</p>
          <p className="mt-0.5 text-[16px] leading-relaxed text-ink-900">{r.what_to_do}</p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[14px] text-ink-600">
          <span className="flex items-center gap-1.5">
            <Move className="h-4 w-4 text-ink-400" strokeWidth={1.8} />
            <span className="font-semibold text-ink-900">{formatDistance(r.distance_m, lang)}</span>
            <span>· {r.travel_min} {t.min}</span>
          </span>
          {visitText && (
            <span className="flex items-center gap-1.5">
              <Clock className="h-4 w-4 text-ink-400" strokeWidth={1.8} />
              {t.onVisit} {visitText} {t.min}
            </span>
          )}
          {r.rating != null && (
            <span className="flex items-center gap-1">
              <Star className="h-4 w-4 fill-sun-500 text-sun-500" strokeWidth={1.5} />
              <span className="font-semibold text-ink-900">{r.rating.toFixed(1)}</span>
            </span>
          )}
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[14px]">
          <OpenStatusLine s={r.open_status} t={t} />
          <span className="inline-flex items-center gap-1.5 text-ink-500">
            <Database className="h-4 w-4 text-ink-400" strokeWidth={1.8} />
            {t.fromDb}
            {srcNames &&
              (srcUrl ? (
                <a href={srcUrl} target="_blank" rel="noreferrer" className="font-medium text-teal-700 underline-offset-2 hover:underline">
                  {srcNames}
                </a>
              ) : (
                <span className="font-medium text-ink-700">{srcNames}</span>
              ))}
          </span>
        </div>
        {r.open_status.label && r.open_status.state !== 'unknown' && (
          <p className="mt-1 text-[13px] text-ink-400">{r.open_status.label}</p>
        )}

        {navLinks.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-[13px] font-semibold text-ink-500">{t.howToGet}</p>
            <NavButtons links={navLinks} note={t.navNote} />
          </div>
        )}

        {badges.length > 0 && (
          <p className="mt-3 text-[14px] text-ink-500">
            {badges.map((b, i) => (
              <span key={b}>
                {i > 0 && <span className="mx-1.5 text-ink-300">/</span>}
                <span className={b === '24_7' ? 'font-semibold text-open' : b === 'budget' ? 'text-sun-600' : ''}>{badgeText(b, lang)}</span>
              </span>
            ))}
          </p>
        )}
      </div>
    </article>
  )
})

export default RecommendationCard
