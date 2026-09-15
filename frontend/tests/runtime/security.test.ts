import { expect, it } from "vitest";
import { isTrustedSender } from "../../electron/main/security";
import {
  restartSchema,
  helpSchema,
  snapshotSchema,
} from "../../electron/shared/bridge-schema";
it.each([
  "https://example.com/",
  "app://ui.evil/",
  "app://ui/other",
  "file:///C:/test",
  "app://ui/?x=1",
  "http://127.0.0.1:5173/",
])("rejects foreign production origin %s", (url) =>
  expect(isTrustedSender(1, 1, true, url, false)).toBe(false),
);
it("requires sender, main frame and exact origin together", () => {
  expect(isTrustedSender(1, 1, true, "app://ui/", false)).toBe(true);
  expect(isTrustedSender(2, 1, true, "app://ui/", false)).toBe(false);
  expect(isTrustedSender(1, 1, false, "app://ui/", false)).toBe(false);
  expect(isTrustedSender(1, 1, true, "http://127.0.0.1:5173/", true)).toBe(
    true,
  );
});
it("rejects arbitrary URLs, extra fields and malformed restart requests", () => {
  for (const value of [
    { expectedGeneration: "1" },
    { expectedGeneration: -1 },
    { expectedGeneration: 1, token: "SECRET_SENTINEL" },
  ])
    expect(restartSchema.safeParse(value).success).toBe(false);
  expect(helpSchema.safeParse({ helpId: "https://example.com" }).success).toBe(
    false,
  );
  expect(
    snapshotSchema.safeParse({ state: "ready", token: "SECRET_SENTINEL" })
      .success,
  ).toBe(false);
});
