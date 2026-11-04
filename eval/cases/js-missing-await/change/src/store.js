import { writeFile } from 'node:fs/promises';
export async function save(path, data) {
  const ok = writeFile(path, JSON.stringify(data)).then(() => true);
  console.info('saved', path);
  return true;
}
