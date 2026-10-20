import type { RecommendResponse } from '../types'
import type { Dict } from '../i18n'

export default function ContextUsed({ result, t }: { result: RecommendResponse; t: Dict }) {
  const c = result.context_used ?? {}
  const pi = result.parsed_intent
  const rows: [string, string, string | undefined | null][] = [
    ['📍', t.ctx_location, c.location],
    ['🕒', t.ctx_time, c.time],
    [/симуляц|simulat|симуляция/i.test(c.weather ?? '') ? '❄️' : '🌡️', t.ctx_weather, c.weather],
    ['🚶', t.ctx_mode, c.mode],
    ['⭕', t.ctx_radius, c.radius_m ? `${(c.radius_m / 1000).toFixed(1).replace('.0', '')} км` : null],
    ['✓', t.ctx_filters, c.filters?.length ? c.filters.join(', ') : null],
    ['🧠', t.ctx_intent, pi ? [pi.intent, ...(pi.keywords ?? [])].filter(Boolean).join(' · ') : null],
    ['🤖', t.ctx_llm, result.llm?.provider ? [result.llm.provider, result.llm.model].filter(Boolean).join(' / ') : null],
  ]
  return (
    <details open className="group rounded-3xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <summary className="flex cursor-pointer list-none items-center justify-between text-lg font-extrabold text-slate-900">
        <span>🔎 {t.contextUsed}</span>
        <span className="text-slate-400 transition group-open:rotate-180">▾</span>
      </summary>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-[15px]">
        {rows
          .filter(([, , v]) => v)
          .map(([icon, k, v]) => (
            <div key={k} className="contents">
              <dt className="whitespace-nowrap text-slate-500">
                {icon} {k}
              </dt>
              <dd className="font-medium text-slate-800">{v}</dd>
            </div>
          ))}
      </dl>
      {c.data_note && (
        <p className="mt-4 flex gap-2 rounded-2xl bg-emerald-50 px-4 py-3 text-[14px] font-medium text-emerald-900">
          <span aria-hidden>🔒</span>
          {c.data_note}
        </p>
      )}
    </details>
  )
}
