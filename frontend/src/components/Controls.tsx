import { Accessibility, Baby, Car, Footprints, House, Minus, Plus, Snowflake, Users } from 'lucide-react'
import type { Dict } from '../i18n'
import { TIME_SLOTS, isoClock, type TimeSlot } from '../geo'
import type { Mode, WeatherOverride } from '../types'

export const WINTER: WeatherOverride = { temp_c: -20, wind_ms: 9 }

export interface ControlsState {
  slot: TimeSlot
  presetTime: string | null // client_time из пресета, пока пользователь не тронул время
  withKids: boolean
  accessibility: boolean
  groupSize: number
  indoorOnly: boolean
  mode: Mode
  weather: WeatherOverride | null // симуляция погоды для демо (weather_override)
}

interface Props {
  t: Dict
  value: ControlsState
  onChange: (v: ControlsState) => void
  slotIso: (s: TimeSlot) => string
}

function Toggle({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-[14px] font-medium transition ${
        active ? 'border-ink-900 bg-ink-900 text-white' : 'border-ink-200 bg-white text-ink-800 hover:border-ink-400'
      }`}
    >
      {children}
    </button>
  )
}

const formatTemp = (c: number) => `${c > 0 ? '+' : c < 0 ? '−' : ''}${Math.abs(c)}°`
const ico = 'h-4 w-4'

export default function Controls({ t, value, onChange, slotIso }: Props) {
  const set = (patch: Partial<ControlsState>) => onChange({ ...value, ...patch })
  const slotLabel = (s: TimeSlot) => t[`slot_${s}` as const]

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <span className="text-[13px] font-semibold text-ink-500">{t.time}</span>
          <span className="text-[15px] font-semibold tabular-nums text-ink-900">
            {value.presetTime ? isoClock(value.presetTime) : isoClock(slotIso(value.slot))}
            {value.presetTime && <span className="ml-1.5 font-normal text-ink-400">· {t.fromPreset}</span>}
          </span>
        </div>
        <div className="grid grid-cols-5 rounded-xl bg-ink-50 p-1" role="radiogroup" aria-label={t.time}>
          {TIME_SLOTS.map((s) => {
            const on = s === value.slot && !value.presetTime
            return (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => set({ slot: s, presetTime: null })}
                className={`rounded-lg py-2 text-[13px] font-semibold transition sm:text-[14px] ${
                  on ? 'bg-white text-ink-900 shadow-sm' : 'text-ink-500 hover:text-ink-900'
                }`}
              >
                {slotLabel(s)}
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <div className="inline-flex rounded-full border border-ink-200 p-0.5" role="radiogroup">
          {(['walk', 'car'] as Mode[]).map((m) => {
            const Icon = m === 'walk' ? Footprints : Car
            return (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={value.mode === m}
                onClick={() => set({ mode: m })}
                className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[14px] font-medium transition ${
                  value.mode === m ? 'bg-teal-500 text-white' : 'text-ink-700 hover:text-ink-900'
                }`}
              >
                <Icon className={ico} strokeWidth={1.8} />
                {m === 'walk' ? t.walk : t.car}
              </button>
            )
          })}
        </div>
        <Toggle active={value.withKids} onClick={() => set({ withKids: !value.withKids })}>
          <Baby className={ico} strokeWidth={1.8} />
          {t.withKids}
        </Toggle>
        <Toggle active={value.accessibility} onClick={() => set({ accessibility: !value.accessibility })}>
          <Accessibility className={ico} strokeWidth={1.8} />
          {t.accessibility}
        </Toggle>
        <Toggle active={value.indoorOnly} onClick={() => set({ indoorOnly: !value.indoorOnly })}>
          <House className={ico} strokeWidth={1.8} />
          {t.indoorOnly}
        </Toggle>
        <Toggle active={!!value.weather} onClick={() => set({ weather: value.weather ? null : WINTER })}>
          <Snowflake className={ico} strokeWidth={1.8} />
          {t.winter} {formatTemp((value.weather ?? WINTER).temp_c)}
        </Toggle>
        <div className="inline-flex items-center gap-1 rounded-full border border-ink-200 py-0.5 pl-3.5 pr-1 text-[14px] font-medium text-ink-800">
          <Users className={ico} strokeWidth={1.8} />
          <span className="ml-1">{t.group}</span>
          <button
            type="button"
            className="ml-1 flex h-8 w-8 items-center justify-center rounded-full hover:bg-ink-50 disabled:opacity-30"
            onClick={() => set({ groupSize: Math.max(1, value.groupSize - 1) })}
            disabled={value.groupSize <= 1}
            aria-label="−"
          >
            <Minus className={ico} strokeWidth={2} />
          </button>
          <span className="w-4 text-center tabular-nums">{value.groupSize}</span>
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-full hover:bg-ink-50 disabled:opacity-30"
            onClick={() => set({ groupSize: Math.min(5, value.groupSize + 1) })}
            disabled={value.groupSize >= 5}
            aria-label="+"
          >
            <Plus className={ico} strokeWidth={2} />
          </button>
        </div>
      </div>
    </div>
  )
}
