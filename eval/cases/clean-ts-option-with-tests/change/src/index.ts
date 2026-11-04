export interface GreetOptions {
  /** Ending punctuation. Defaults to "!" (the previous behaviour). */
  punctuation?: string;
}

export function greet(name: string, options: GreetOptions = {}): string {
  const { punctuation = '!' } = options;
  return `Hello, ${name}${punctuation}`;
}
