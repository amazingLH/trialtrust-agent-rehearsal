import { readFile, writeFile } from 'node:fs/promises';

// Snapshots are copied from trialtrust/web by sync-workbench.mjs. Cloud builds
// need only this frontend folder; no Python source or credentials are uploaded.
const source = new URL('../src/workbench/', import.meta.url);
const names = ['portal_viewport.js', 'workbench_tools.js', 'auth.js', 'app.js'];
const scripts = await Promise.all(names.map(async name =>
  (await readFile(new URL(name + '.txt', source), 'utf8')).replace(/\r\n/g, '\n')));
// Keep the shared helper local to this ES module. Its CommonJS wrapper would
// otherwise be detected by the bundler, leaving globalThis.WorkbenchTools empty.
const marker = '})(typeof globalThis !== "undefined" ? globalThis : this, function () {';
const factoryStart = scripts[1].indexOf(marker);
const factoryEnd = scripts[1].lastIndexOf('});');
if (factoryStart < 0 || factoryEnd <= factoryStart || scripts[1].slice(factoryEnd + 3).trim()) {
  throw new Error('Shared workbench helper wrapper changed; update the module adapter before building.');
}
scripts[1] = 'const WorkbenchTools = (() => {\n' +
  scripts[1].slice(factoryStart + marker.length, factoryEnd) + '\n})();';
await writeFile(new URL('../src/workbench-entry.js', import.meta.url),
  '/* Generated from the shared workbench. Do not edit. */\n' +
  'import { bridgeFetch as fetch } from "./services/workbenchService";\n' + scripts.join('\n'), 'utf8');
