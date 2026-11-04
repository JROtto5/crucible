// retry(fn, { delayMs }) retries fn up to 3 times, waiting delayMs between attempts.
export async function retry(fn, { delayMs = 500 } = {}) {
  for (let i = 0; ; i++) {
    try { return await fn(); } catch (e) {
      if (i === 2) throw e;
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
}
