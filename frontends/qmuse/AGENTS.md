# QMuse local project

This is a QMuse React and Vite project. Preserve the existing Vite, TanStack Router, Tailwind, and QMuse Runtime conventions. Reuse existing components and dependencies before adding new ones.

Install dependencies with `cnpm install` when available, otherwise use `npm install`. Run `npm run check` and `npm run build` after changes. Never read, print, or commit `.env*`, tokens, cookies, credentials, or private configuration. Do not edit platform bindings in `.qmuse/project.json` manually.

# QMuse Cloud Context

This project uses QMuse local import mode.

For database, cloud backend, data persistence, data management, database-field changes, authentication, permissions, secrets, or cloud functions, call the `load_skill` tool to load the `qmuse-cloud` skill before creating or modifying schema, service, function, authentication, or database configuration files. If `load_skill` is unavailable, read `.agents/skills/qmuse-cloud/SKILL.md` and follow the packaged official Skill.

Follow the loaded `qmuse-cloud` skill and its references as the source of truth. If the relevant rules are no longer visible in recent context, reload or reread the skill before continuing cloud-service work.

In all user-visible reasoning, progress updates, and final responses, refer to this capability as "QMuse 云服务". Do not expose underlying provider or product names, package names, or internal architecture unless the user explicitly asks. This naming rule does not change source-code identifiers, dependencies, configuration keys, or API paths; follow the loaded skill for those implementation details.

Cloud resources are declared in source and applied by `qmuse import`. Never place QMuse cloud management credentials in browser code or local scripts.

Before the first successful import, local development cannot connect to QMuse 云服务 because the app identity and development cloud resources do not exist yet. Validate the UI, build, and cloud resource declarations locally. Test-only mocks are allowed, but do not replace QMuse cloud behavior in production code with localStorage, an in-memory fake API, fabricated runtime context, or another local fallback.

After `qmuse import` succeeds, validate real authentication, create/read/update/delete operations, permissions, and persistence after refresh at the returned QMuse preview URL. A local preview is not evidence that QMuse 云服务 works. Later `qmuse import .` runs update the app bound in `.qmuse/project.json`.

Keep local images in `src/assets` or `public/assets`. Use static Vite imports, literal `new URL(..., import.meta.url)`, CSS `url()`, or `/assets/...` for files under `public/assets`. Do not construct asset paths dynamically or use expiring signed URLs.

When the project is ready, run `qmuse import .`. Use `qmuse import configure` if the task requests public configuration or cloud confirmation. There is no `qmuse push` command.

If import fails and `.qmuse/last-import-error.json` exists, read its structured diagnostics, fix the reported source or dependency issue, rerun `npm run check` and `npm run build`, then retry `qmuse import .`. Do not edit the diagnostic file or platform bindings to bypass validation. For platform, infrastructure, or policy failures, report the category to the user instead of changing application code blindly.
