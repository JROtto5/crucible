// PATCH /me: apply a partial update to the signed-in user's profile.
// A field that is absent is left as it is; a field sent as null is cleared.
export type Profile = { displayName: string; bio?: string; avatarUrl?: string; pronouns?: string };

export function applyPatch(profile: Profile, patch: Record<string, unknown>): Profile {
  const next: Record<string, unknown> = { ...profile };
  for (const [key, value] of Object.entries(patch)) {
    if (!(key in next) && !["bio", "avatarUrl", "pronouns"].includes(key)) continue;
    if (value === null) delete next[key];
    else next[key] = value;
  }
  return next as Profile;
}
