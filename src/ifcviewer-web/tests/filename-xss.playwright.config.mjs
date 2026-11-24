// This file was generated with the assistance of an AI coding tool.
import { defineConfig } from '@playwright/test';

// Runs the filename-XSS specs against system Chrome. Headless, and without
// the WebGPU smoke-test server: these cases drive the page's own model-list
// code, which inserts the name before a sidecar is parsed.
export default defineConfig({
  testDir: '.',
  testMatch: 'filename-xss.spec.mjs',
  timeout: 30_000,
  reporter: [['list']],
  use: {
    channel: 'chrome',
    headless: true,
  },
});
