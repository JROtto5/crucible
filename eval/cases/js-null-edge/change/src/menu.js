import { displayName } from './profile.js';
export function header(session) {
  return `Signed in as ${displayName(session.user)}`;
}
