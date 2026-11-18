// Profile settings form: send only what the user edited.
export type Edits = Partial<{ displayName: string; bio: string; avatarUrl: string; pronouns: string }>;

export function buildPatch(edits: Edits): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(edits)) {
    if (value !== undefined) patch[key] = value;
  }
  return patch;
}

export async function save(edits: Edits, fetchImpl: typeof fetch = fetch): Promise<number> {
  const res = await fetchImpl("/me", { method: "PATCH", body: JSON.stringify(buildPatch(edits)) });
  return res.status;
}
