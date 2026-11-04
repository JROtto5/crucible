// retry(fn, { delay }) retries fn up to 3 times, waiting `delay` seconds between attempts.
export async function retry(fn, { delay = 0.5 } = {}) {
  for (let i = 0; ; i++) {
    try { return await fn(); } catch (e) {
      if (i === 2) throw e;
      await new Promise(r => setTimeout(r, delay));
    }
  }
}
