import { execSync } from 'node:child_process';
// `name` comes straight from the upload form.
export function thumbPath(name) {
  return `thumbs/${name}.png`;
}
export function makeThumb(name) {
  execSync(`convert uploads/${name} -resize 128x128 ${thumbPath(name)}`);
}
