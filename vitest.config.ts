import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["frontend/tests/**/*.test.ts"],
    environment: "happy-dom",
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["frontend/**/*.ts"],
      exclude: ["frontend/tests/**"],
    },
  },
});
