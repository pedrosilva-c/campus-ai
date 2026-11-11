// Test helper: prints, one JSON per line, what the extension would produce for a projection file:
//   1. the adapter result {ok, snapshot|code, summary}
//   2. the hello message
//   3. the page_report message built exactly as background.js builds it (only when the adapter succeeded)
// Usage: node emit_tiles.mjs <projection.json> <session-token> <page-url>
import { readFileSync } from 'node:fs';
import { buildTilesSnapshot } from '../src/tiles_adapter.js';
import { classifyPage } from '../src/classify.js';
import { buildHello, buildPageReport } from '../src/protocol.js';

const [projectionPath, session, url] = process.argv.slice(2);
const projection = JSON.parse(readFileSync(projectionPath, 'utf8'));
const built = buildTilesSnapshot(projection, { now: new Date('2026-11-05T20:00:00Z') });
const out = (value) => process.stdout.write(JSON.stringify(value) + '\n');
out(built);
out(buildHello());
if (built.ok) out(buildPageReport(session, classifyPage(url), built.snapshot));
