import { writeFile } from 'node:fs/promises';
export async function save(path, data) {
  await writeFile(path, JSON.stringify(data));
  return true;
}
