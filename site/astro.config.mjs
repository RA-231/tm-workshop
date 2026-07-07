import { defineConfig, passthroughImageService } from "astro/config";
import starlight from "@astrojs/starlight";

// https://astro.build/config
export default defineConfig({
  // Where the site is served in the workshop stack (used for the sitemap).
  site: "http://localhost:4321",
  // The docs have no images to optimize, so skip sharp entirely — keeps the
  // Alpine build image tiny and avoids sharp's native-binary dance.
  image: { service: passthroughImageService() },
  integrations: [
    starlight({
      title: "Space Telemetry",
      tagline: "A Space Summit 2026 workshop",
      social: [],
      // The workshop pages are generated from ../docs by scripts/transform-docs.mjs.
      sidebar: [
        { label: "Overview", link: "/overview/" },
        { label: "1 · Ingest", link: "/ingest/" },
        { label: "2 · Query", link: "/query/" },
        { label: "3 · Chat", link: "/chat/" },
        { label: "4 · MCP Server", link: "/mcp-server/" },
      ],
    }),
  ],
});
