// This file was generated with the assistance of an AI coding tool.
import path from "node:path";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { svelteTesting } from "@testing-library/svelte/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
    plugins: [svelte({ hot: false }), svelteTesting()],
    resolve: {
        alias: {
            $lib: path.resolve("./src/lib"),
            $src: path.resolve("./src"),
        },
    },
    test: {
        environment: "jsdom",
        include: ["tests/**/*.test.ts"],
        testTimeout: 60000,
        hookTimeout: 60000,
    },
});
