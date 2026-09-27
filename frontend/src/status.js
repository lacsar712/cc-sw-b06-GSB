// 领取进程状态码 → 中文
export const STATUS_TEXT = {
  pending: '待处理',
  processing: '领取中',
  done: '已结案',
}

export const EVENT_TEXT = {
  claim: '首次领取',
  reassign: '改派',
  complete: '结案',
}

export function statusText(s) {
  return STATUS_TEXT[s] || s || '—'
}

export function eventText(k) {
  return EVENT_TEXT[k] || k
}

export function fmtTime(t) {
  if (!t) return '—'
  const d = new Date(t)
  if (Number.isNaN(d.getTime())) return t
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
