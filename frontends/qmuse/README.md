# TrialTrust hosted workbench

React/Vite entry for the shared TrialTrust interface. The existing Python service
continues to own account authentication, records, model calls and verification.
The browser contains only a public API endpoint and its own opaque account token.

From this folder, run `npm install`, `npm run check`, then `npm run build`.
After changing `trialtrust/web`, run `node tools/sync-workbench.mjs` here and
commit the refreshed snapshots with the original source. Use `--check` to verify
that the snapshots match. Snapshots allow this directory to build independently.

The browser bridge only accepts explicitly enabled origins, fixed local routes,
and the existing account/session headers. It does not proxy external URLs or
relax record ownership. It removes ambient cookies and never automatically
replays requests. Existing first-party account routes retain their CSRF checks.

App bindings stay in the ignored `.qmuse` folder. Import this directory with the
official CLI in external-backend mode; subsequent imports update the same app.
