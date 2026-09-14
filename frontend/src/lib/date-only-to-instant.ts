// Code-review finding #12 (2026-09-14): `<input type="date">` produces a bare `YYYY-MM-DD` string
// with no timezone information. Sending that string as-is let the backend's "naive datetime -> treat
// as UTC" convention (`crud._as_aware_utc`) silently reinterpret the user's LOCAL calendar date as a
// UTC one, shifting the real deadline by hours — a full day for timezones far from UTC. Neither side
// was wrong in isolation; no contract ever said which timezone a bare date implies.
//
// Fix: resolve the ambiguity here, while the browser's real local timezone is still known, and send
// an already-qualified instant across the wire — the backend's `datetime` fields already accept ISO
// 8601 with an offset correctly, so nothing on that side needs to change.
//
// `new Date(year, month, day, ...)` (unlike `new Date(dateOnlyString)`, which parses as UTC midnight)
// resolves the date using the browser's actual local timezone. A deadline means "done by the end of
// this day", so this returns that day's last instant, not its first.
export function dateOnlyToEndOfDayIso(dateOnly: string): string {
  const [year, month, day] = dateOnly.split("-").map(Number);
  return new Date(year, month - 1, day, 23, 59, 59, 999).toISOString();
}
