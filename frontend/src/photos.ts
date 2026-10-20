import type { CategoryPhotos, ImageRef } from './types'

/**
 * Запасные фото на случай, если /api/category-photos недоступен. Файлы не копируются в репозиторий —
 * изображения грузятся с серверов Wikimedia; авторы и лицензии — в public/CREDITS.md.
 */
export const FALLBACK_PHOTOS: CategoryPhotos = {
  // Копия обложек из data/category_photos.json (Команда данных) — только ссылки и атрибуция, файлы не копируются.
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

/** Можно ли показывать фото категории как иллюстрацию: нейтральный кадр или снятое в Астане без привязки к месту. */
function usableIllustration(img: ImageRef): boolean {
  return img.generic === true || (img.astana === true && !img.poi_id)
}

// Если у категории нет подходящих иллюстраций — берём из близких по смыслу (не из случайных).
const RELATED: Record<string, string[]> = {
  cafe: ['restaurant', 'bar'],
  restaurant: ['cafe'],
  bar: ['nightlife', 'restaurant'],
  nightlife: ['bar'],
  kids: ['playground', 'entertainment'],
  playground: ['kids', 'park'],
  entertainment: ['kids', 'cinema'],
  convenience: ['supermarket', 'market', 'shop'],
  supermarket: ['convenience', 'market'],
  market: ['supermarket'],
  shop: ['mall', 'clothes'],
  clothes: ['shop', 'mall'],
  mall: ['shop', 'clothes'],
  pharmacy: [],
  wellness: ['sport'],
  sport: ['wellness'],
  museum: ['gallery'],
  gallery: ['museum'],
  theatre: ['cinema'],
  cinema: ['theatre', 'entertainment'],
  monument: ['landmark', 'viewpoint'],
  viewpoint: ['landmark', 'monument'],
  landmark: ['monument', 'viewpoint'],
  park: ['landmark'],
  library: ['coworking'],
  coworking: ['library', 'cafe'],
}

/**
 * Иллюстрации для карточек без своего фото: детерминированно по poi_id, по возможности без повторов в одной выдаче.
 * Фото другого конкретного места (с чужим poi_id) не используется никогда; заглушка — только если нет ничего.
 */
export function assignIllustrations(
  recs: { poi_id: string; category: string; image?: ImageRef | null }[],
  categories: Record<string, ImageRef[]>,
): (ImageRef | null)[] {
  const used = new Set<string>()
  for (const r of recs) if (r.image) used.add(r.image.url)
  return recs.map((r) => {
    if (r.image) return null
    let list: ImageRef[] = []
    for (const c of [r.category, ...(RELATED[r.category] ?? [])]) {
      list = (categories[c] ?? []).filter(usableIllustration)
      if (list.length) break
    }
    if (!list.length) return null
    const start = list.indexOf(pickBySeed(list, r.poi_id)!)
    for (let k = 0; k < list.length; k++) {
      const img = list[(start + k) % list.length]
      if (!used.has(img.url)) {
        used.add(img.url)
        return img
      }
    }
    return list[start] // все уже показаны — лучше повтор, чем пустой блок
  })
}
