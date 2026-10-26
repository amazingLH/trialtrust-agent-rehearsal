import { copyFile, readFile } from 'node:fs/promises';

const source = new URL('../../../trialtrust/web/', import.meta.url);
const snapshot = new URL('../src/workbench/', import.meta.url);
for (const name of ['index.html', 'style.css', 'portal_viewport.js', 'workbench_tools.js', 'auth.js', 'app.js']) {
  const from = new URL(name, source), to = new URL(name + '.txt', snapshot);
  if (process.argv.includes('--check')) {
    if (!(await readFile(from)).equals(await readFile(to))) throw new Error(`Workbench snapshot is stale: ${name}`);
  } else await copyFile(from, to);
}
