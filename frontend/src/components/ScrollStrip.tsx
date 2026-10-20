import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

/** Горизонтальная лента: затухание по краям, где есть скрытое содержимое, и стрелки прокрутки. */
export default function ScrollStrip({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [edges, setEdges] = useState({ left: false, right: false })

  const update = () => {
    const el = ref.current
    if (!el) return
    const left = el.scrollLeft > 4
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 4
    setEdges((e) => (e.left === left && e.right === right ? e : { left, right }))
  }
  useEffect(() => {
    update()
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(update)
    ro.observe(el)
    for (const c of Array.from(el.children)) ro.observe(c)
    return () => ro.disconnect()
  })

  const fade = 36
  const mask = `linear-gradient(to right, ${edges.left ? 'transparent' : '#000'} 0, #000 ${fade}px, #000 calc(100% - ${fade}px), ${edges.right ? 'transparent' : '#000'} 100%)`
  const scroll = (dir: number) => ref.current?.scrollBy({ left: dir * Math.max(200, (ref.current?.clientWidth ?? 300) * 0.7), behavior: 'smooth' })
  const arrow =
    'absolute top-1/2 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-ink-200 bg-white text-ink-900 shadow-sm transition hover:border-ink-900'

  return (
    <div className="relative">
      <div
        ref={ref}
        onScroll={update}
        className={`no-scrollbar flex overflow-x-auto ${className}`}
        style={{ maskImage: mask, WebkitMaskImage: mask }}
      >
        {children}
      </div>
      {edges.left && (
        <button type="button" aria-label="←" onClick={() => scroll(-1)} className={`${arrow} left-0`}>
          <ChevronLeft className="h-4 w-4" strokeWidth={2} />
        </button>
      )}
      {edges.right && (
        <button type="button" aria-label="→" onClick={() => scroll(1)} className={`${arrow} right-0`}>
          <ChevronRight className="h-4 w-4" strokeWidth={2} />
        </button>
      )}
    </div>
  )
}
