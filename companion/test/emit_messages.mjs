// Test helper: prints, one per line, the JSON messages the extension would send for a snapshot file.
// Used by tests/test_companion_extension.py to prove the Python host accepts what the JS side builds.
// Usage: node emit_messages.mjs <snapshot.json> <session-token>
import { readFileSync } from 'node:fs';
import { buildHello, buildPageReport } from '../src/protocol.js';
import { classifyPage } from '../src/classify.js';

const [snapshotPath, session] = process.argv.slice(2);
const snapshot = JSON.parse(readFileSync(snapshotPath, 'utf8'));
const page = classifyPage('https://ead.aedb.br/ava/course/view.php?id=7653');
process.stdout.write(JSON.stringify(buildHello()) + '\n');
process.stdout.write(JSON.stringify(buildPageReport(session, page, snapshot)) + '\n');
