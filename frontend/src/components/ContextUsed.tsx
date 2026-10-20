import { Bot, Brain, ChevronDown, Clock, Footprints, MapPin, Radius, ShieldCheck, SlidersHorizontal, Thermometer } from 'lucide-react'
import type { RecommendResponse } from '../types'
import type { Dict } from '../i18n'

export default function ContextUsed({ result, t }: { result: RecommendResponse; t: Dict }) {
  const c = result.context_used ?? {}
  const pi = result.parsed_intent
  const rows = [
    [MapPin, t.ctx_location, c.location],
    [Clock, t.ctx_time, c.time],
    [Thermometer, t.ctx_weather, c.weather],
    [Footprints, t.ctx_mode, c.mode],
    [Radius, t.ctx_radius, c.radius_m ? `${(c.radius_m / 1000).toFixed(1).replace('.0', '')} ${t.km}` : null],
    [SlidersHorizontal, t.ctx_filters, c.filters?.length ? c.filters.join('; ') : null],
    [Brain, t.ctx_intent, pi ? [pi.intent, ...(pi.keywords ?? [])].filter(Boolean).join(' · ') : null],
    [Bot, t.ctx_llm, result.llm?.provider ? [result.llm.provider, result.llm.model].filter(Boolean).join(' / ') : null],
  ] as const
  return (
    <details open className="group border-t border-ink-100 pt-5">
      <summary className="flex cursor-pointer list-none items-center justify-between">
        <span className="font-display text-[18px] font-semibold text-ink-900">{t.contextUsed}</span>
        <ChevronDown className="h-5 w-5 text-ink-400 transition group-open:rotate-180" strokeWidth={1.8} />
      </summary>
      <dl className="mt-3 divide-y divide-ink-100 text-[14px]">
        {rows
          .filter(([, , v]) => v)
          .map(([Icon, k, v]) => (
            <div key={k} className="grid grid-cols-[22px_minmax(96px,auto)_1fr] items-start gap-x-2 py-2">
              <Icon className="mt-0.5 h-4 w-4 text-ink-400" strokeWidth={1.8} />
              <dt className="text-ink-500">{k}</dt>
              <dd className="text-ink-900">{v}</dd>
            </div>
          ))}
      </dl>
      {c.data_note && (
        <p className="mt-3 flex gap-2 text-[13px] leading-snug text-ink-500">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" strokeWidth={1.8} />
          {c.data_note}
        </p>
      )}
    </details>
  )
}
