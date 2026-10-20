/** Date lisible d'une conversation : « 14:05 » aujourd'hui, « hier, 14:05 », puis « 12 oct. » ou « 12 oct. 2025 ». */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(date)) / 86_400_000);
  if (days === 0) return `Aujourd'hui, ${time}`;
  if (days === 1) return `Hier, ${time}`;
  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}
