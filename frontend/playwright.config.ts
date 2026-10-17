// Fluxos de ponta a ponta da interface (F1.H15). Rodam contra a interface
// compilada (npm run build), servida pela API local de verdade, com um
// workspace temporário e um token aleatório.

import { randomBytes } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// O processo principal define e os workers herdam (o config é carregado de
// novo em cada worker).
process.env.WOLFZ_E2E_TOKEN ??= randomBytes(24).toString("base64url");
process.env.WOLFZ_E2E_HOME ??= mkdtempSync(join(tmpdir(), "wolfz-e2e-"));

const porta = Number(process.env.WOLFZ_E2E_PORT ?? 8798);
const python =
  process.env.WOLFZ_PYTHON ??
  (process.platform === "win32" ? "../.venv/Scripts/python.exe" : "../.venv/bin/python");

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${porta}`,
    trace: "retain-on-failure",
    viewport: { width: 1400, height: 900 },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 900 } },
    },
  ],
  webServer: {
    command: `"${python}" ../scripts/servidor_teste.py --port ${porta} --home "${process.env.WOLFZ_E2E_HOME}"`,
    url: `http://127.0.0.1:${porta}/`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "pipe",
  },
});
