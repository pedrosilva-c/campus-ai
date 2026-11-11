// Test helper: runs the REAL preview logic (src/preview.js) over projections that a real Chromium produced
// from synthetic pages (tests/test_companion_chromium.py). The fake API only replays those projections.
// Input: JSON {scenario: {url, identity: {href, projection}, full: {href, projection}}}. Output: JSON
// {scenario: {state, messageKey, mode, rows, issues, labels, matches, coverage, diagnostic}}.
import { readFileSync } from 'node:fs';
import { MESSAGES, runPreview } from '../src/preview.js';

const scenarios = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const [name, s] of Object.entries(scenarios)) {
  const api = {
    tabs: { query: async () => [{ id: 1, url: s.url }] },
    scripting: {
      executeScript: async (o) => (o.files ? [{}] : [{ result: o.args[0].withEntries ? s.full : s.identity }]),
    },
  };
  const model = await runPreview(api, { now: new Date('2026-11-05T20:00:00Z') });
  out[name] = {
    state: model.state,
    messageKey: Object.keys(MESSAGES).find((k) => MESSAGES[k] === model.message) || '',
    mode: model.mode,
    rows: model.rows.map((r) => [r.cmid, r.modtype, r.kind, r.classe]),
    issues: model.issues.length,
    labels: model.labels,
    matches: model.comparison ? model.comparison.matches : null,
    coverage: model.coverage,
    diagnostic: model.diagnostic,
  };
}
process.stdout.write(JSON.stringify(out));
