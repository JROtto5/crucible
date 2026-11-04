/** Public API. */
export function formatDate(locale: string, date: Date): string {
  return date.toLocaleDateString(locale);
}
