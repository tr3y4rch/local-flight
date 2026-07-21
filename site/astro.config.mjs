import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://beacontools.cc",
  output: "static",
  trailingSlash: "always",
  outDir: "./dist",
  publicDir: "./public",
  build: {
    format: "directory",
  },
  devToolbar: {
    enabled: false,
  },
});
