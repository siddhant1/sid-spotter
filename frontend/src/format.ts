export function duration(seconds: number): string {
  const mins = Math.round(seconds / 60)
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}

const timeFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
const tzFmt = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })

export const clock = (iso: string | number | Date) => timeFmt.format(new Date(iso))

export const tzName = () => tzFmt.formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value ?? ''

export const num = (v: number | null | undefined, digits = 0) => (v == null ? '–' : v.toFixed(digits))

export const miles = (v: number) => `${Math.round(v).toLocaleString()} mi`

/** Value for <input type="datetime-local"> in local time. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
