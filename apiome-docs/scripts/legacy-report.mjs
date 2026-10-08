#!/usr/bin/env node
/**
 * Print the "Legacy screens changed" note for the weekly screenshot refresh (DOCS-1.10, #5627).
 *
 * Usage: git diff --name-only | node scripts/legacy-report.mjs
 *
 * Reads changed paths on stdin, and prints Markdown naming every `legacy`-tagged entry in
 * `screens.json` whose image changed — or nothing when none did. See `legacyReport` in
 * scripts/lib/screens.mjs.
 */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {legacyReport, loadManifest} from './lib/screens.mjs';

const siteDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const {screens} = loadManifest(path.join(siteDir, 'screens.json'));
const changedFiles = fs.readFileSync(0, 'utf8').split('\n').filter(Boolean);
const report = legacyReport({screens, changedFiles});
if (report) console.log(report);
