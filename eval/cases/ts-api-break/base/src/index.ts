/** Public API. */
export function formatDate(date: Date, locale: string = 'en-US'): string {
  return date.toLocaleDateString(locale);
}
