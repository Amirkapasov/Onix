import type { Dict } from '../i18n'
import { TIME_SLOTS, isoClock, type TimeSlot } from '../geo'
import type { Mode, WeatherOverride } from '../types'

export const WINTER: WeatherOverride = { temp_c: -20, wind_ms: 9 }

export interface ControlsState {
  slot: TimeSlot
  presetTime: string | null // client_time из пресета, пока пользователь не тронул ползунок
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

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center gap-2 rounded-full border-2 px-4 py-2 text-[15px] font-semibold transition ${
        active
          ? 'border-sky-600 bg-sky-600 text-white shadow-sm'
          : 'border-slate-200 bg-white text-slate-700 hover:border-sky-300 hover:bg-sky-50'
      }`}
    >
      {children}
    </button>
  )
}

const formatTemp = (c: number) => `${c > 0 ? '+' : c < 0 ? '−' : ''}${Math.abs(c)}°`

export default function Controls({ t, value, onChange, slotIso }: Props) {
  const set = (patch: Partial<ControlsState>) => onChange({ ...value, ...patch })
  const idx = TIME_SLOTS.indexOf(value.slot)
  const shownTime = value.presetTime ? isoClock(value.presetTime) : isoClock(slotIso(value.slot))
  const slotLabel = (s: TimeSlot) => t[`slot_${s}` as const]

  return (
    <div className="space-y-4">
      {/* Время суток */}
      <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div className="mb-2 flex items-baseline justify-between">
          <span className="text-sm font-bold uppercase tracking-wide text-slate-500">🕒 {t.time}</span>
          <span className="text-2xl font-extrabold tabular-nums text-slate-900">
            {shownTime}
            {value.presetTime && <span className="ml-2 text-sm font-medium text-slate-500">· {t.fromPreset}</span>}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={TIME_SLOTS.length - 1}
          step={1}
          value={idx}
          onChange={(e) => set({ slot: TIME_SLOTS[Number(e.target.value)], presetTime: null })}
          className="time-range w-full"
          aria-label={t.time}
        />
        <div className="mt-1 grid grid-cols-5 text-center text-[13px] font-semibold sm:text-sm">
          {TIME_SLOTS.map((s, i) => (
            <button
              key={s}
              type="button"
              onClick={() => set({ slot: s, presetTime: null })}
              className={`rounded-md py-1 ${
                i === idx && !value.presetTime ? 'text-sky-700' : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              {slotLabel(s)}
            </button>
          ))}
        </div>
      </div>

      {/* Фильтры */}
      <div className="flex flex-wrap gap-2">
        <Chip active={value.withKids} onClick={() => set({ withKids: !value.withKids })}>
          🧒 {t.withKids}
        </Chip>
        <Chip active={value.accessibility} onClick={() => set({ accessibility: !value.accessibility })}>
          ♿ {t.accessibility}
        </Chip>
        <Chip active={value.indoorOnly} onClick={() => set({ indoorOnly: !value.indoorOnly })}>
          🏠 {t.indoorOnly}
        </Chip>
        <Chip active={!!value.weather} onClick={() => set({ weather: value.weather ? null : WINTER })}>
          ❄️ {t.winter} {formatTemp((value.weather ?? WINTER).temp_c)}
        </Chip>
        <div className="flex items-center gap-1 rounded-full border-2 border-slate-200 bg-white py-1 pl-4 pr-1 text-[15px] font-semibold text-slate-700">
          👥 {t.group}
          <button
            type="button"
            className="ml-1 h-8 w-8 rounded-full text-lg hover:bg-slate-100 disabled:opacity-30"
            onClick={() => set({ groupSize: Math.max(1, value.groupSize - 1) })}
            disabled={value.groupSize <= 1}
            aria-label="−"
          >
            −
          </button>
          <span className="w-5 text-center tabular-nums">{value.groupSize}</span>
          <button
            type="button"
            className="h-8 w-8 rounded-full text-lg hover:bg-slate-100 disabled:opacity-30"
            onClick={() => set({ groupSize: Math.min(5, value.groupSize + 1) })}
            disabled={value.groupSize >= 5}
            aria-label="+"
          >
            +
          </button>
        </div>
        <div className="flex rounded-full border-2 border-slate-200 bg-white p-0.5 text-[15px] font-semibold">
          {(['walk', 'car'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => set({ mode: m })}
              aria-pressed={value.mode === m}
              className={`rounded-full px-4 py-1.5 transition ${
                value.mode === m ? 'bg-amber-400 text-slate-900 shadow-sm' : 'text-slate-600 hover:bg-slate-50'
              }`}
            >
              {m === 'walk' ? `🚶 ${t.walk}` : `🚗 ${t.car}`}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
