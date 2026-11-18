// Profile settings form. Emptying a text box now clears that field on the server.
export type Edits = Partial<{ displayName: string; bio: string; avatarUrl: string; pronouns: string }>;

const CLEARABLE = ["bio", "avatarUrl", "pronouns"] as const;

export function buildPatch(edits: Edits): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  if (edits.displayName !== undefined) patch.displayName = edits.displayName.trim();
  for (const key of CLEARABLE) {
    patch[key] = edits[key]?.trim() || null;
  }
  return patch;
}

export async function save(edits: Edits, fetchImpl: typeof fetch = fetch): Promise<number> {
  const res = await fetchImpl("/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildPatch(edits)),
  });
  return res.status;
}
