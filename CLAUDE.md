# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **Detailing Aid (DA) Converter** for pharma e-detailing. Users upload a PDF (or a ZIP of existing HTML slides), draw interactive hotspots on each slide in a browser workbench, and download a ZIP of **SFE-compliant** HTML slides ("Detailing Aid") that run on Veeva-style CLM players / iPads. SFE compliance (touch swipe, aspect-ratio locking, no external network calls, specific JS bootstrapping) is the core constraint driving most backend logic — comments marked `SFE COMPLIANCE` / `SFE RULE` flag these requirements.

## Repo layout

- `backend/` — FastAPI app. Nearly all logic lives in the single file `backend/main.py`.
- `frontend/` — Angular 18 SPA. Effectively one component: `frontend/src/app/app.component.ts` (+ `.html`/`.css`).
- `backend/templates/` — Static SFE assets injected into generated slides: `css/style.css`, `js/control.js` (swipe/aspect-ratio runtime), `js/jquery.min.js`, `js/tracking.js`.
- `compare_working/` and `compare_failing/` — Reference sample outputs (real SFE HTML). Diff against these when debugging why generated output fails on a real player.
- `node-v20.12.2-darwin-arm64/`, `*.zip`, `sample_dt/`, `amlot_dt/`, `temp_sample/` — bundled toolchain and test/sample data, not application code.

## Commands

Backend (from `backend/`):
```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000    # dev server on :8000
```

Frontend (from `frontend/`):
```bash
npm install
npm start          # ng serve → http://localhost:4200
npm run build      # → frontend/dist/
npm test           # Karma + Jasmine (single run: ng test --watch=false)
```

There is no backend test suite. `backend/test_ppt.scpt` is a one-line AppleScript (quits PowerPoint), not a test.

## Deployment

- **Backend** → Docker (`backend/Dockerfile`, `python:3.11-slim`) on Railway, listening on port **8000**. Storage path switches to `/app/storage` when `/app` exists, else `./storage`.
- **Frontend** → Vercel (`frontend/vercel.json` rewrites all routes to `index.html`). The API base URL is read at runtime from `window.__ENV_API_BASE__`, defaulting to `http://localhost:8000` (see `API_BASE` in `app.component.ts`).

## Backend architecture (`main.py`)

Flow: **upload → (draw hotspots in frontend) → generate → download**.

- **Persistence is a flat JSON file**, not a database: `projects_db` (in-memory dict) is mirrored to `storage/projects.json` via `save_db()`/`load_db()`. Every mutating endpoint must call `save_db()`. Per-project files live under `storage/{project_id}/`: `images/`, `slides/`, `media/`, and the generated `build/` + `output.zip`.
- **`fitz` (PyMuPDF) is imported lazily inside functions**, never at module top level — a top-level import crashed startup. Keep it that way.
- **Upload** (`POST /upload`): PDF pages are rasterized to PNG at `zoom=3` with `cropbox=mediabox` (prevents footer-button clipping); page text is used to auto-suggest an HTML filename via `generate_filename`. ZIP uploads are sanitized with BeautifulSoup (external `http(s)` links neutralized, `onload` and external `<script>` removed). **PPTX is explicitly rejected** — users must convert to PDF first.
- **Generate** (`POST /generate/{project_id}`): builds slides **only for the selected pages** into `build/`, rewrites hotspot targets through a `rename_map` (page id → final `.html` name), and always forces the first selected page to `index.html`. Then zips `build/` to `output.zip`.
- **`get_base_html(...)`** is the HTML generator and the heart of the system. It assembles each slide from a template plus injected `SFE_STYLE`/`SFE_CONTROL`/`SFE_JQUERY`/`SFE_TRACKING`, and honors **two output formats** (see below). Hotspot types: `home`, `nav` (link to another slide), `menu`/`popup` (opens an overlay list). Navigation targets live in `data-next-file` / `data-previous-file` attributes that `control.js` reads.

### Output formats (`output_format`)

`get_base_html` and the ZIP path branch heavily on this — verify both when touching generation:

- **`v9`** (default): jQuery and `control.js` are **inlined** into each HTML file. Hotspots/links are `<a href>` tags. Image paths use `./images/`.
- **`sfe+`**: jQuery and `control.js` are referenced **externally** (`js/control.js`, `js/jquery.min.js` written into `build/js/`). Hotspots become `<div data-next-file>` instead of `<a>`. Image/media paths are rewritten to drop the leading `./` (`images/`, `media/`). `control.js` includes a click/touch polyfill so `data-next-file` divs still navigate in a plain browser preview.

## Frontend architecture

Single standalone `AppComponent` (no router — `app.routes.ts` is empty). Everything is client-side state:

- **Workbench interaction**: mouse-drag on a slide creates rectangles as percentages (not pixels) so they scale with the aspect-ratio-locked player. `drawingMode` (`video | home | nav | menu`) decides whether a drag positions the video or creates a hotspot. `replicateHotspot` copies a hotspot across selected slides.
- **State is a `pages[]` array** posted back to `/generate`; each page carries `hotspots[]`, `video_*` position fields, `new_html_name`, and `selected`. Page 0 is locked to `index.html` and cannot be deselected.
- Global settings sent with generation: `navArrowsPosition`, `homePosition`, `outputFormat`.

## Gotchas

- Percentages everywhere: hotspot/video coordinates are stored as percent of slide dimensions on both ends — don't convert to pixels.
- When adding fields to a page, update the `load_db()` sanitizer defaults so old projects.json entries don't break.
- CORS is wide open (`allow_origins=["*"]`) and a global exception handler returns 500s with CORS headers — intentional, so browser errors surface instead of being masked as CORS failures.
