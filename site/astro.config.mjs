// @ts-check
import { defineConfig } from "astro/config";

// Arabic is the default language for a Lebanese audience — a choice made at scaffold
// time (docs/BUILD_PLAN.md §5), not a decision from the brief. Every page lives under
// /ar, /en or /fr; the root redirects to /ar/.
export default defineConfig({
  output: "static",
  i18n: {
    locales: ["ar", "en", "fr"],
    defaultLocale: "ar",
    routing: { prefixDefaultLocale: true },
  },
});
