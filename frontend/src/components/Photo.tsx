import { useMemo, useState } from 'react'
import type { ImageRef } from '../types'
import type { Dict } from '../i18n'
import { cleanAuthor, imgSrc } from '../photos'
import { categoryIcon } from './Icons'

interface Props {
  image?: ImageRef | null // фото самого места
  illustration?: ImageRef | null // фото категории — помечается «иллюстрация»
  category: string
  alt: string
  t: Dict
  className?: string // соотношение сторон и скругление
  children?: React.ReactNode // оверлей (номер и т.п.)
}

/** Фото с обязательной атрибуцией: место → иллюстрация категории → цветовой блок с линейной иконкой. */
export default function Photo({ image, illustration, category, alt, t, className = '', children }: Props) {
  // Порядок попыток: миниатюра места → оригинал места → миниатюра иллюстрации → оригинал → цветовой блок.
  const candidates = useMemo(() => {
    const out: { img: ImageRef; src: string; kind: 'place' | 'illustration' }[] = []
    for (const [img, kind] of [[image, 'place'], [illustration, 'illustration']] as const) {
      if (!img) continue
      const thumb = imgSrc(img)
      out.push({ img, src: thumb, kind })
      if (img.url && img.url !== thumb) out.push({ img, src: img.url, kind })
    }
    return out
  }, [image, illustration])
  const [failed, setFailed] = useState(0)
  const current = candidates[failed]
  const Icon = categoryIcon(category)

  return (
    <figure>
      <div className={`relative overflow-hidden bg-ink-100 ${className}`}>
        {current ? (
          <img
            key={current.src}
            src={current.src}
            alt={alt}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setFailed((f) => f + 1)}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center bg-ink-50">
            <Icon className="h-10 w-10 text-ink-300" strokeWidth={1.4} />
          </div>
        )}
        {children}
      </div>
      {current && <Credit img={current.img} t={t} illustration={current.kind === 'illustration'} />}
    </figure>
  )
}

export function Credit({ img, t, illustration = false, light = false }: { img: ImageRef; t: Dict; illustration?: boolean; light?: boolean }) {
  const author = cleanAuthor(img.author) || t.authorUnknown
  return (
    <figcaption className={`mt-1.5 truncate text-[11px] leading-tight ${light ? 'text-white/80' : 'text-ink-400'}`}>
      {illustration && <span className={light ? 'text-white' : 'text-ink-500'}>{t.illustration} · </span>}
      <a href={img.page_url} target="_blank" rel="noreferrer" className="hover:underline">
        {t.photoBy}: {author}
      </a>
      {' · '}
      {img.license_url ? (
        <a href={img.license_url} target="_blank" rel="noreferrer" className="hover:underline">
          {img.license}
        </a>
      ) : (
        img.license
      )}
    </figcaption>
  )
}
