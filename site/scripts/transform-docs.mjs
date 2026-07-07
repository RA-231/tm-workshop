// Generate Starlight doc pages from the canonical workshop docs in ../docs.
//
// docs/ stays the single source of truth (readable straight on GitHub). This
// script copies each NN-name.md into src/content/docs/name.md with:
//   - Starlight frontmatter (title from the H1, sidebar order from NN)
//   - inter-doc links rewritten to Starlight routes (01-ingest.md -> /ingest/)
//   - links to repo source files de-linked (they aren't served by the site)
//
// Runs automatically before `astro dev` / `astro build` (see package.json).

import { readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SRC = process.env.DOCS_SRC || join(here, "..", "..", "docs");
const OUT = join(here, "..", "src", "content", "docs");

// NN-name.md -> route slug "name"
const slugOf = (file) => file.replace(/^\d+-/, "").replace(/\.md$/, "");
const orderOf = (file) => parseInt(file.slice(0, 2), 10);

const files = readdirSync(SRC).filter((f) => /^\d\d-.*\.md$/.test(f));
const slugByFile = new Map(files.map((f) => [f, slugOf(f)]));

mkdirSync(OUT, { recursive: true });

function rewriteLinks(md) {
  return md.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (whole, text, href) => {
    // Another workshop doc -> Starlight route, preserving any #anchor.
    const docMatch = href.match(/^(\d\d-[\w-]+)\.md(#.*)?$/);
    if (docMatch) {
      const target = files.find((f) => f.startsWith(docMatch[1]));
      if (target) return `[${text}](/${slugByFile.get(target)}/${docMatch[2] || ""})`;
    }
    // External link -> leave as-is.
    if (/^(https?:|mailto:|#)/.test(href)) return whole;
    // Anything else is a repo-relative path to a source file the site does not
    // serve. Drop the link but keep the (usually already code-formatted) text.
    return text;
  });
}

let count = 0;
for (const file of files) {
  const raw = readFileSync(join(SRC, file), "utf8");
  const lines = raw.split("\n");

  // Pull the first H1 as the page title and drop that line.
  const h1Index = lines.findIndex((l) => /^#\s+/.test(l));
  const title = h1Index >= 0 ? lines[h1Index].replace(/^#\s+/, "").trim() : slugOf(file);
  if (h1Index >= 0) lines.splice(h1Index, 1);

  const body = rewriteLinks(lines.join("\n").replace(/^\n+/, ""));
  const frontmatter = [
    "---",
    `title: ${JSON.stringify(title)}`,
    `sidebar:`,
    `  order: ${orderOf(file)}`,
    "---",
    "",
  ].join("\n");

  writeFileSync(join(OUT, `${slugOf(file)}.md`), frontmatter + body);
  count++;
}

console.log(`transform-docs: generated ${count} pages from ${SRC}`);
