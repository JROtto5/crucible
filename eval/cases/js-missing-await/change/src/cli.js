import { save } from './store.js';
export async function run(path, data) {
  await save(path, data);
  process.exit(0);
}
