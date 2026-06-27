/**
 * vitest.config.ts
 *
 * Vitest configuration for the frontend shell component tests.
 *
 * - environment: jsdom (browser-like DOM for React component rendering)
 * - @vitejs/plugin-react: transforms JSX/TSX and handles React-specific features
 * - setupFiles: injects @testing-library/jest-dom matchers before every test
 * - alias: mirrors the Next.js `@/*` path alias from tsconfig.json
 *
 * Traces: frontend-shell-001 … frontend-shell-022 (test infrastructure)
 */

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    globals: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
