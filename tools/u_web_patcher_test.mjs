// Runs the web patcher's core (docs/patcher/patcher-core.js) on a real .patch in Node and compares every
// result with the package it was made from, byte for byte:
//   node tools/u_web_patcher_test.mjs PATCH ORIGINAL_DATA_DIR PACKAGE_DIR
import { openAsBlob } from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { applyPatch } from '../docs/patcher/patcher-core.js';

const [patchPath, original, pkg] = process.argv.slice(2);
if (!pkg) {
  console.error('usage: node tools/u_web_patcher_test.mjs PATCH ORIGINAL_DATA_DIR PACKAGE_DIR');
  process.exit(2);
}
const started = Date.now();
let mismatches = 0;
let lastPrint = 0;
const header = await applyPatch(await openAsBlob(patchPath), {
  readOriginal: async (disc) => {
    try { return new Uint8Array(await readFile(path.join(original, disc))); } catch { return null; }
  },
  writeOutput: async (out, bytes) => {
    const expected = new Uint8Array(await readFile(path.join(pkg, out)));
    if (expected.length !== bytes.length || Buffer.compare(Buffer.from(expected), Buffer.from(bytes)) !== 0) {
      mismatches++;
      console.log('MISMATCH', out);
    }
  },
  onProgress: ({ done, total, bytes }) => {
    if (Date.now() - lastPrint > 5000 || done === total) {
      lastPrint = Date.now();
      console.log(`${done}/${total} files, ${(bytes / 1e6).toFixed(1)} MB`);
    }
  },
});
console.log(`${header.name} v${header.version}: ${mismatches ? mismatches + ' mismatch(es)' : 'every file identical to the package'}` +
  ` (${((Date.now() - started) / 1000).toFixed(1)} s)`);
process.exit(mismatches ? 1 : 0);
