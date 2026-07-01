import { defineConfig } from "vite";

// https://vitejs.dev/config/
export default defineConfig({
  // ---------------------------------------------------------------------------
  // Build Configuration
  // ---------------------------------------------------------------------------
  // 'outDir' specifies where production build output goes.
  // This is the directory that would be served by a static host or Docker.
  // ---------------------------------------------------------------------------
  build: {
    outDir: "dist",
  },

  // ---------------------------------------------------------------------------
  // Test Configuration (Vitest)
  // ---------------------------------------------------------------------------
  // Vitest reads its config from the same vite.config file by default.
  // 'globals: true' enables describe/it/expect without explicit imports.
  // 'environment: node' is fine for non-DOM tests; switch to 'jsdom' or
  // 'happy-dom' when component tests are added later.
  // ---------------------------------------------------------------------------
  test: {
    globals: true,
    environment: "node",
  },
});
