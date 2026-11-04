export function total(lines) {
  let t = 0;
  for (const l of lines) t += l.price * l.qty;
  return t;
}
