import type { CategoryPhotos, ImageRef } from './types'

/**
 * Запасные фото на случай, если /api/category-photos недоступен. Файлы не копируются в репозиторий —
 * изображения грузятся с серверов Wikimedia; авторы и лицензии — в public/CREDITS.md.
 */
export const FALLBACK_PHOTOS: CategoryPhotos = {
  // Копия обложек из data/category_photos.json (Агент 1) — только ссылки и атрибуция, файлы не копируются.
  hero: [
    {
      "url": "https://upload.wikimedia.org/wikipedia/commons/a/a5/Night_at_Esil_District%2C_Astana_%28P1190721%29.jpg",
      "thumb_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a5/Night_at_Esil_District%2C_Astana_%28P1190721%29.jpg/960px-Night_at_Esil_District%2C_Astana_%28P1190721%29.jpg",
      "page_url": "https://commons.wikimedia.org/wiki/File:Night_at_Esil_District,_Astana_(P1190721).jpg",
      "author": "Matti Blume",
      "license": "CC BY-SA 4.0",
      "license_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.en",
      "source": "wikimedia_commons"
    },
    {
      "url": "https://upload.wikimedia.org/wikipedia/commons/b/b4/Khan_Shatyr.jpg",
      "thumb_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/b/b4/Khan_Shatyr.jpg/960px-Khan_Shatyr.jpg",
      "page_url": "https://commons.wikimedia.org/wiki/File:Khan_Shatyr.jpg",
      "author": "Quarot",
      "license": "CC0",
      "license_url": "http://creativecommons.org/publicdomain/zero/1.0/deed.en",
      "source": "wikimedia_commons"
    },
    {
      "url": "https://upload.wikimedia.org/wikipedia/commons/4/42/Central_Downtown_Astana_pamorama.jpg",
      "thumb_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/42/Central_Downtown_Astana_pamorama.jpg/960px-Central_Downtown_Astana_pamorama.jpg",
      "page_url": "https://commons.wikimedia.org/wiki/File:Central_Downtown_Astana_pamorama.jpg",
      "author": "Ken and Nyetta",
      "license": "CC BY 2.0",
      "license_url": "https://creativecommons.org/licenses/by/2.0",
      "source": "wikimedia_commons"
    },
    {
      "url": "https://upload.wikimedia.org/wikipedia/commons/3/38/%D0%90%D1%81%D1%82%D0%B0%D0%BD%D0%B0%2C_EXPO-2017_%D1%81%D0%B2%D0%B5%D1%80%D1%85%D1%83.jpg",
      "thumb_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/38/%D0%90%D1%81%D1%82%D0%B0%D0%BD%D0%B0%2C_EXPO-2017_%D1%81%D0%B2%D0%B5%D1%80%D1%85%D1%83.jpg/960px-%D0%90%D1%81%D1%82%D0%B0%D0%BD%D0%B0%2C_EXPO-2017_%D1%81%D0%B2%D0%B5%D1%80%D1%85%D1%83.jpg",
      "page_url": "https://commons.wikimedia.org/wiki/File:%D0%90%D1%81%D1%82%D0%B0%D0%BD%D0%B0,_EXPO-2017_%D1%81%D0%B2%D0%B5%D1%80%D1%85%D1%83.jpg",
      "author": "Nikolai Bulykin",
      "license": "CC BY-SA 4.0",
      "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
      "source": "wikimedia_commons"
    },
    {
      "url": "https://upload.wikimedia.org/wikipedia/commons/6/66/Sunny_January_Day_on_Astana%27s_Ishim_River_%286658586715%29.jpg",
      "thumb_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/66/Sunny_January_Day_on_Astana%27s_Ishim_River_%286658586715%29.jpg/960px-Sunny_January_Day_on_Astana%27s_Ishim_River_%286658586715%29.jpg",
      "page_url": "https://commons.wikimedia.org/wiki/File:Sunny_January_Day_on_Astana%27s_Ishim_River_(6658586715).jpg",
      "author": "Ken and Nyetta",
      "license": "CC BY 2.0",
      "license_url": "https://creativecommons.org/licenses/by/2.0",
      "source": "wikimedia_commons"
    }
  ],
  categories: {},
}

export const cleanAuthor = (a: string) => a.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim()

/** Стабильный выбор фото категории для места (одно и то же место — одно и то же фото). */
export function pickBySeed<T>(items: T[] | undefined, seed: string): T | null {
  if (!items?.length) return null
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0
  return items[Math.abs(h) % items.length]
}

export const imgSrc = (i: ImageRef) => i.thumb_url || i.url

/** Иллюстрации категорий для выдачи без повторов: одно фото — максимум одной карточке. */
export function assignIllustrations(
  recs: { poi_id: string; category: string; image?: ImageRef | null }[],
  categories: Record<string, ImageRef[]>,
): (ImageRef | null)[] {
  const used = new Set<string>()
  for (const r of recs) if (r.image) used.add(r.image.url)
  return recs.map((r) => {
    if (r.image) return null
    // Иллюстрация — только снятое в Астане и не фото другого конкретного места (свой poi_id).
    // Зарубежные кадры часто с чужими вывесками и надписями (иероглифы, грузинский ларёк) — вместо них заглушка категории.
    const list = (categories[r.category] ?? []).filter((img) => img.astana === true && (!img.poi_id || img.poi_id === r.poi_id))
    if (!list.length) return null
    const start = list.indexOf(pickBySeed(list, r.poi_id)!)
    for (let k = 0; k < list.length; k++) {
      const img = list[(start + k) % list.length]
      if (!used.has(img.url)) {
        used.add(img.url)
        return img
      }
    }
    return null // все фото категории уже показаны — лучше цветовой блок, чем повтор
  })
}
