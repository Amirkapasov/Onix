/** Қошқар мүйіз — «бараньи рога», классический казахский орнамент. Используется один раз, в шапке. */
export default function Ornament({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 32" className={className} aria-hidden fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M32 30V17c0-7 6-12 12-10.5 5.5 1.4 6 8.6 1.2 9.6-3.6.8-5.4-2.6-3-4.3" />
      <path d="M32 17c0-7-6-12-12-10.5-5.5 1.4-6 8.6-1.2 9.6 3.6.8 5.4-2.6 3-4.3" />
      <path d="M44 22c4.4 0 8 2.6 10 6M20 22c-4.4 0-8 2.6-10 6" />
    </svg>
  )
}
