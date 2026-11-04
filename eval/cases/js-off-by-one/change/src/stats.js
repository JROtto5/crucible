export function sum(xs) {
  let s = 0;
  for (const x of xs) s += x;
  return s;
}

// Mean of a non-empty array of numbers.
export function mean(xs) {
  let s = 0;
  for (let i = 0; i <= xs.length; i++) s += xs[i];
  return s / xs.length;
}
