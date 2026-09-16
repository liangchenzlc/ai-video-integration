import { expect, test, vi } from "vitest";
const mocks = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("electron", () => ({ ipcRenderer: { invoke: mocks.invoke } }));
import { settingsBridge } from "../../electron/preload/settings";
import { projectsBridge } from "../../electron/preload/projects";
test("both settings read bridges reject provider payloads containing secrets", async () => {
  mocks.invoke.mockResolvedValue({
    ok: true,
    data: {
      revision: 1,
      ffmpegConfigured: false,
      providers: [
        {
          providerId: "safe",
          credentialConfigured: true,
          maskedSuffix: "1234",
          storageConfigured: false,
          secret: "secret-sentinel",
        },
      ],
      capabilities: [],
    },
  });
  for (const read of [settingsBridge.get, projectsBridge.media.settings]) {
    const result = await read();
    expect(result.ok).toBe(false);
    expect(JSON.stringify(result)).not.toContain("secret-sentinel");
  }
});
test("preload validates credential input and remaps malicious backend messages", async () => {
  mocks.invoke.mockClear();
  const invalid = await settingsBridge.setCredential({
    providerId: "../../private",
  } as never);
  expect(invalid).toMatchObject({
    ok: false,
    error: { code: "REQUEST_INVALID" },
  });
  expect(mocks.invoke).not.toHaveBeenCalled();
  mocks.invoke.mockResolvedValue({
    ok: false,
    error: { code: "CREDENTIAL_ENCRYPTION_FAILED", message: "secret-sentinel" },
  });
  const result = await settingsBridge.get();
  expect(result).toMatchObject({
    ok: false,
    error: { code: "CREDENTIAL_ENCRYPTION_FAILED" },
  });
  expect(JSON.stringify(result)).not.toContain("secret-sentinel");
});
