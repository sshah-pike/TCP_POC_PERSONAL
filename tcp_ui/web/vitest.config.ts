import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

// Component tests (jsdom). The assistant API module is mocked in the tests: no server, no network.
export default mergeConfig(viteConfig, defineConfig({
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"], restoreMocks: true, testTimeout: 15000 },
}));
