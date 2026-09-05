// Deliberately not clsx/tailwind-merge — this slice's components never pass conflicting Tailwind
// classes that need de-duplication, just conditional ones. Add tailwind-merge if that changes.
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
