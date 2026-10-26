import { readFile, writeFile } from 'node:fs/promises';

// Snapshots are copied from trialtrust/web by sync-workbench.mjs. Cloud builds
// need only this frontend folder; no Python source or credentials are uploaded.
const source = new URL('../src/workbench/', import.meta.url);
const names = ['portal_viewport.js', 'workbench_tools.js', 'auth.js', 'app.js'];
const scripts = await Promise.all(names.map(name => readFile(new URL(name + '.txt', source), 'utf8')));
scripts[1] = scripts[1].replace(
  'if (typeof module === "object" && module.exports) module.exports = api;\n  else root.WorkbenchTools = api;',
  'root.WorkbenchTools = api;',
);
scripts[1] += '\nconst WorkbenchTools = globalThis.WorkbenchTools;';
await writeFile(new URL('../src/workbench-entry.js', import.meta.url),
  '/* Generated from the shared workbench. Do not edit. */\n' +
  'import { bridgeFetch as fetch } from "./services/workbenchService";\n' + scripts.join('\n'), 'utf8');
