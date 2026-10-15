# STF digital twin - notes for coding assistants

Read `README.md` first; it maps the repository. The essentials:

- **One model, proven before export.** `stf-cad/hbw/` holds the parametric model of the
  fischertechnik factory and its proofs. `hbw_export.py` refuses to write `web/public/*.json`
  unless every proof passes. Never hand-edit the files in `web/public/`; regenerate them.
- **Variants.** `STF_VARIANT=up1 ... up12` selects an upgrade level (`variant.py`). The web app
  shows `up12`. `validate.py` re-proves every variant and checks their export fingerprints.
- **Web** (`web/src`): `shared/` (data loading, model types, theme), `twin/` (the shell and the
  view/panel registries - add a view or panel there), `panels/`, `views/`, `scene/` (three.js),
  `dashboard/`. A standalone build (`npm run build:pages`) runs without the API.
- **API** (`services/api`): FastAPI + WebSocket. Commands are guarded (`security.py`); keep the
  Vite proxy's `changeOrigin: false`. See `docs/SECURITY.md`.
- **Tests:** `make test`, `make lint`, `cd web && npx tsc --noEmit -p .`.
