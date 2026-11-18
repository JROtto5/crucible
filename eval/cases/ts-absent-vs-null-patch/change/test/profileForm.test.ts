import { describe, expect, it } from "vitest";
import { buildPatch } from "../src/profileForm";

describe("buildPatch", () => {
  it("clears a field the user emptied", () => {
    expect(buildPatch({ bio: "  " }).bio).toBeNull();
  });
  it("trims the display name", () => {
    expect(buildPatch({ displayName: " Ada " }).displayName).toBe("Ada");
  });
  it("keeps an edited bio", () => {
    expect(buildPatch({ bio: "hi" }).bio).toBe("hi");
  });
});
