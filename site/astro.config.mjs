import { defineConfig } from "astro/config";
import { resolveDeployment } from "./deployment.mjs";

export default defineConfig({
  site: resolveDeployment().siteOrigin,
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
