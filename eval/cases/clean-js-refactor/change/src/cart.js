const lineTotal = (l) => l.price * l.qty;

export function total(lines) {
  let t = 0;
  for (const l of lines) t += lineTotal(l);
  return t;
}
