#!/usr/bin/env node
// Data-driven batch renderer for poster series (e.g. 小红书多图笔记):
// fills {{TOKEN}} placeholders of ONE shared template per page, then calls
// render.mjs for each page. {{PAGE}}/{{TOTAL}} are auto-filled as 01/04-style
// counters (a page may override them with its own PAGE/TOTAL values).
//
// Usage:
//   node render-series.mjs --template ../templates/social-post-series.html \
//     --data series.json --outdir out/ [--width 1080] [--height 1440] [--format png]
// data JSON: { "width": 1080, "height": 1440, "shared": { "BRAND": "..." }, "pages": [ { "TITLE": "..." }, ... ] }
import * as fs from 'fs';
import * as path from 'path';
import { spawnSync } from 'child_process';
import { fileURLToPath } from 'url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const RENDER = path.join(SCRIPT_DIR, 'render.mjs');

function error(msg) { console.error(`Error: ${msg}`); process.exit(1); }

const args = process.argv.slice(2);
function opt(name) {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? undefined : args[i + 1];
}

const templateFile = opt('template');
const dataFile = opt('data');
const outDir = opt('outdir');
if (!templateFile) error("'--template <file>' is required (the shared series template).");
if (!dataFile) error("'--data <file>' is required (JSON with optional width/height, shared, pages).");
if (!outDir) error("'--outdir <dir>' is required.");

const template = fs.readFileSync(templateFile, 'utf-8');
const data = JSON.parse(fs.readFileSync(dataFile, 'utf-8'));
const pages = data.pages;
if (!Array.isArray(pages) || pages.length === 0) error('data JSON must contain a non-empty "pages" array.');

const width = Number(opt('width')) || data.width || 1080;
const height = Number(opt('height')) || data.height || 1440;
const formatOpt = opt('format');
const format = (formatOpt || 'png').toLowerCase();

fs.mkdirSync(outDir, { recursive: true });
const pad = n => String(n).padStart(Math.max(2, String(pages.length).length), '0');
for (const [i, page] of pages.entries()) {
  const tokens = { PAGE: pad(i + 1), TOTAL: pad(pages.length), ...(data.shared || {}), ...page };
  const filled = template.replace(/\{\{(\w+)\}\}/g, (raw, key) => {
    if (tokens[key] === undefined) { console.error(`Warning: page ${i + 1}: no value for {{${key}}}, left as-is`); return raw; }
    return String(tokens[key]);
  });
  const base = path.join(outDir, pad(i + 1));
  fs.writeFileSync(`${base}.html`, filled, 'utf-8');
  const r = spawnSync(process.execPath, [
    RENDER, '--html', `${base}.html`, '-o', `${base}.${format}`,
    '--width', String(width), '--height', String(height),
    ...(formatOpt ? ['--format', format] : [])
  ], { stdio: 'inherit' });
  if (r.status !== 0) { console.error(`Error: page ${i + 1} failed; stopping.`); process.exit(1); }
}
console.log(`OK series: ${pages.length} pages (${width}x${height}) -> ${outDir}`);
