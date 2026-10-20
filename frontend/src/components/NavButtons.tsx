import { ArrowUpRight, Navigation } from 'lucide-react'

/** Явные кнопки «открыть в навигаторе» (зона нажатия ≥ 44 px). Открываются в новой вкладке / приложении. */
export default function NavButtons({ links, note }: { links: { id: string; label: string; url: string }[]; note?: string }) {
  return (
    <div className="flex flex-wrap gap-2" title={note}>
      {links.map((l) => (
        <a
          key={l.id}
          href={l.url}
          target="_blank"
          rel="noopener noreferrer"
          className="group inline-flex min-h-11 items-center gap-2 rounded-xl border border-ink-300 bg-white px-3.5 text-[14px] font-semibold text-ink-900 transition hover:border-ink-900 hover:bg-ink-900 hover:text-white active:scale-[0.98]"
        >
          <Navigation className="h-4 w-4 text-teal-600 transition group-hover:text-sun-500" strokeWidth={2} />
          {l.label}
          <ArrowUpRight className="h-4 w-4 text-ink-400 transition group-hover:text-white" strokeWidth={2} />
        </a>
      ))}
    </div>
  )
}
