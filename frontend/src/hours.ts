/**
 * Упрощённый разбор OSM opening_hours — только для «горящих» точек на ночной карте
 * (рекомендации берут статус с сервера). Понимает «24/7», «Mo-Su 10:00-22:00», «Mo-Fr 09:00-18:00; Sa 10:00-16:00»,
 * несколько интервалов через запятую, интервалы через полночь и «off». Остальное — null (неизвестно).
 */
const DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function parseDays(spec: string): Set<number> | null {
  const out = new Set<number>()
  for (const part of spec.split(',')) {
    const [a, b] = part.split('-')
    const i = DAYS.indexOf(a)
    const j = b ? DAYS.indexOf(b) : i
    if (i < 0 || j < 0) return null
    for (let k = i; ; k = (k + 1) % 7) {
      out.add(k)
      if (k === j) break
    }
  }
  return out
}

const toMin = (hm: string) => {
  const [h, m] = hm.split(':').map(Number)
  return h * 60 + m
}

/** Открыто ли в момент iso (время Астаны берём из строки как есть). true/false/null. */
export function isOpenAt(oh: string | null | undefined, iso: string): boolean | null {
  if (!oh) return null
  const s = oh.trim()
  if (s === '24/7') return true
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  if (!m) return null
  const day = (new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay() + 6) % 7 // 0 = Mo
  const now = +m[4] * 60 + +m[5]
  const prev = (day + 6) % 7
  let result: boolean | null = null
  for (const raw of s.split(';')) {
    const rule = raw.trim()
    if (!rule) continue
    const mm = rule.match(/^(?:([A-Za-z,\- ]+?)\s+)?(off|closed|\d{1,2}:\d{2}-\d{1,2}:\d{2}(?:\s*,\s*\d{1,2}:\d{2}-\d{1,2}:\d{2})*)$/)
    if (!mm) return null
    const days = mm[1] ? parseDays(mm[1].replace(/\s/g, '')) : new Set([0, 1, 2, 3, 4, 5, 6])
    if (!days) return null
    if (mm[2] === 'off' || mm[2] === 'closed') {
      if (days.has(day)) result = false
      continue
    }
    for (const span of mm[2].split(',')) {
      const [a, b] = span.trim().split('-').map(toMin)
      const open =
        b > a
          ? days.has(day) && now >= a && now < b
          : (days.has(day) && now >= a) || (days.has(prev) && now < b) // интервал через полночь
      if (open) result = true
    }
  }
  return result ?? false // день не упомянут в правилах — по OSM это «закрыто»
}

/** Вечер/ночь для карты: 19:00–06:00 по времени запроса. */
export function isNightIso(iso: string): boolean {
  const m = iso.match(/T(\d{2}):/)
  if (!m) return false
  const h = +m[1]
  return h >= 19 || h < 6
}
