import {
  Baby, Binoculars, BookOpen, Building2, Camera, Clapperboard, Coffee, Drama, Dumbbell, Footprints, FerrisWheel,
  Landmark, Laptop, MapPin, Moon, Palette, Pill, Plane, Shirt, ShoppingBag, ShoppingCart, Snowflake, Store, Trees,
  Utensils, Waves, Wine, type LucideIcon,
} from 'lucide-react'

export const CATEGORY_ICON: Record<string, LucideIcon> = {
  cafe: Coffee, restaurant: Utensils, bar: Wine, nightlife: Moon, museum: Landmark, gallery: Palette, theatre: Drama,
  cinema: Clapperboard, park: Trees, viewpoint: Binoculars, monument: Landmark, landmark: Camera, religious: Building2,
  mall: ShoppingBag, playground: Baby, kids: Baby, entertainment: FerrisWheel, sport: Dumbbell, library: BookOpen,
  coworking: Laptop, market: Store, supermarket: ShoppingCart, convenience: Store, clothes: Shirt, shop: ShoppingBag,
  pharmacy: Pill, wellness: Waves, other: MapPin,
}

export const categoryIcon = (c: string): LucideIcon => CATEGORY_ICON[c] ?? MapPin

/** Сценарий → линейная иконка и категория для фото плитки (эмодзи из API не используем). */
export function presetVisual(id: string, label: string): { Icon: LucideIcon; category: string } {
  const s = `${id} ${label}`.toLowerCase()
  if (/winter|зим|−20|-20|мороз/.test(s)) return { Icon: Snowflake, category: 'mall' }
  if (/shop|store|магазин|супермаркет|дүкен|24\/7|24_7/.test(s)) return { Icon: ShoppingCart, category: 'supermarket' }
  if (/kid|child|реб|дет|бала/.test(s)) return { Icon: Baby, category: 'playground' }
  if (/night|ноч|түн/.test(s)) return { Icon: Moon, category: 'nightlife' }
  if (/airport|аэропорт|вылет|flight/.test(s)) return { Icon: Plane, category: 'landmark' }
  if (/coffee|кофе|cafe|кафе|розет/.test(s)) return { Icon: Coffee, category: 'cafe' }
  if (/expo|экспо|unusual|необыч/.test(s)) return { Icon: Landmark, category: 'museum' }
  if (/pool|swim|бассейн|spa|спа/.test(s)) return { Icon: Waves, category: 'wellness' }
  if (/walk|прогул|mega|park|парк/.test(s)) return { Icon: Footprints, category: 'park' }
  return { Icon: MapPin, category: 'landmark' }
}
