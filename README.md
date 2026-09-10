# Construction Drawing Annotator

Sign in with Google, upload a multi-page drawing set, move through sheets with the arrow keys,
and mark regions to **block** (red) or **capture** (green). Nothing reaches the database until
you press **Save** — except deleting a rectangle, which takes effect at once.

Built to the spec in [`PRD.md`](./PRD.md) — React + TypeScript, Django + DRF, Render (Postgres +
web service). Supabase is not used for anything in this repo yet; it is reserved for Auth in a
future change.

---

## Quick start

No accounts or credentials needed to run it locally: it falls back to SQLite, on-disk file
storage, and an email-only dev sign-in.

```bash
# 1. Backend  (terminal one)
python3.12 -m venv .venv
.venv/bin/pip install -r api/requirements.txt
cd api && ../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py runserver 8000

# 2. Frontend (terminal two)
cd web && npm install && npm run dev
```

Open <http://localhost:5173>.

### Google sign-in

Put your OAuth **Web application** client id in two places — the frontend sends it, the backend
verifies against it, and they must match or the token is rejected as having the wrong audience:

```bash
# web/.env.local      (Vite inlines this at BUILD time — restart the dev server after editing)
VITE_GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com

# then start Django with the same value
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com ../.venv/bin/python manage.py runserver 8000
```

In the Google Cloud console, the client's **Authorized JavaScript origins** must list the exact
origin you load the app from — `http://localhost:5173`. `http://127.0.0.1:5173` is a *different*
origin to Google; add it too if you use it, or Google refuses with an `origin_mismatch`.

Leave `VITE_GOOGLE_CLIENT_ID` unset and the sign-in card falls back to an email-only form that
works with no credentials at all. That fallback is `DEBUG`-gated and cannot be enabled on a
deployed instance.

**There is no CORS to configure.** Vite proxies `/api` to Django, so the browser sees a single
origin — the same shape as production, where Django serves the SPA itself. The dev server uses
`strictPort`, so if 5173 is busy it stops with an error instead of quietly moving to 5174 and
leaving the app on an origin the API was never told about.

If you would rather have the SPA call Django directly, that is a real cross-origin setup and
needs three settings together:

```bash
# web/.env.local
VITE_API_BASE_URL=http://127.0.0.1:8000

# then start Django with:
REFRESH_COOKIE_SAMESITE=None REFRESH_COOKIE_SECURE=1 ../.venv/bin/python manage.py runserver 8000
```

The cookie flags are not optional. A `SameSite=Strict` cookie is never attached to a cross-site
request, so sign-in would appear to work and then every reload would look like a logout. Django
refuses to start if you set `SameSite=None` without `Secure`, rather than letting the browser
discard the cookie silently. In `DEBUG`, any `localhost`/`127.0.0.1` port is an accepted
origin.

No sample PDF came with the brief, so there is a generator for one:

```bash
.venv/bin/python scripts/make_sample_pdf.py 8 sample-drawings.pdf
```

## Using it

| Input | Does |
| --- | --- |
| <kbd>→</kbd> <kbd>↓</kbd> <kbd>PageDown</kbd> | Next sheet |
| <kbd>←</kbd> <kbd>↑</kbd> <kbd>PageUp</kbd> | Previous sheet |
| <kbd>1</kbd> / <kbd>2</kbd> | Block tool / Capture tool |
| Click and drag | Draw a rectangle |
| Click a rectangle | Select it and open a Delete popover |
| <kbd>Delete</kbd> <kbd>Backspace</kbd> | Delete the selected rectangle |
| <kbd>⌘Z</kbd> / <kbd>Ctrl+Z</kbd> | Undo |
| <kbd>⌘S</kbd> / <kbd>Ctrl+S</kbd> | Save |
| <kbd>Esc</kbd> | Deselect |

## Tests

```bash
cd api && ../.venv/bin/python -m pytest     # 77 tests
cd web && npm test                          # 35 tests
```

The backend suite concentrates on the two places a bug is most expensive: **ownership
isolation** (a second user must not reach the first user's projects, drawings, annotations, or
PDF bytes — and must get a 404, not a 403, so ids cannot be enumerated) and **bulk-save
semantics** (idempotent retries, scoped replacement, all-or-nothing transactions, and that
deleting one rectangle never touches the folder around it). The frontend suite covers
coordinate normalization, the save buffer, and the saved-versus-unsaved delete path. A third
backend file pins the cross-origin rules: any loopback port is allowed in `DEBUG`, no origin is
in production, and a hostname that merely contains "localhost" is refused. Google sign-in is
covered by mocking `google-auth`'s verification — what is tested is that a token is never
trusted unverified, that one Google account maps to exactly one user however often they sign
in, and that a mismatched client id explains itself.

## How it fits together

```
Browser (React SPA)  ──fetch──►  Django + DRF (gunicorn)  ──►  Render Postgres
        │                              │
        │                              ├── WhiteNoise serves the SPA build
        │                              └── mints signed URLs ──────────┐
        └──────PUT the PDF directly──────────────────────────►  on-disk storage (this process)
```

One Render web service serves both halves, so the SPA and the API share an origin and the
refresh cookie can stay `SameSite=Strict` with no CORS. The Postgres database is a second
Render-managed resource (`render.yaml`'s `databases:` block), wired into the web service via
`DATABASE_URL`.

Three tables and a user: `Project` (a folder, and the one PDF it holds) → `Drawing` (one sheet,
the id annotations hang off) → `Annotation`. PRD §7.1 explains why there is no `DrawingFile`
table and what to change if a folder should ever hold several PDFs.

A few decisions worth knowing before reading the code:

- **The PDF never passes through the main DRF view.** Django mints a signed upload URL against
  its own storage endpoint, and the browser PUTs the bytes there directly, then registers the
  file. That keeps a 60 MB drawing set off the request path that also runs serialization and
  auth — even though, with storage on local disk, it is still this same process handling the
  bytes. `api/drawings/storage.py`.
- **Storage is on-disk, not persistent on Render's free plan.** There is no attached disk, so an
  uploaded PDF survives requests and idle periods but is lost on every deploy or restart. Fine
  for this project's scope; a real deployment would need a paid instance with a persistent disk,
  or a real object store.
- **Annotations are stored as fractions of the page, never pixels.** That is what keeps a
  rectangle in place across zoom levels and window sizes. `web/src/lib/geometry.ts`.
- **Django is the only authority on access.** No storage credential of any kind reaches the
  browser, and every file URL expires in five minutes.
- **Annotation ids come from the client**, which makes a retried save idempotent — a dropped
  response cannot turn one rectangle into two.
- **Deleting is the one edit that does not wait for Save.** Clicking a rectangle opens a
  popover whose Delete button calls
  `DELETE /api/projects/{id}/annotations/{annotationId}/` straight away. A rectangle that was
  drawn but never saved is simply dropped from the buffer — there is nothing on the server to
  delete. PRD §9.5 covers the trade-off. Note the annotation id is *in the path*:
  `DELETE /api/projects/{id}/` on its own deletes the entire folder.

## Configuration

Everything has a working local default. Copy `.env.example` to `.env` to change any of it.

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | SQLite | Render Postgres connection string in production — set automatically by `render.yaml`'s `fromDatabase` wiring, no manual entry needed |
| `LOCAL_STORAGE_ROOT` | `api/.localstorage` | Where uploaded PDFs live; not persistent on Render's free plan (see above) |
| `GOOGLE_CLIENT_ID` | unset → dev sign-in | Must equal `VITE_GOOGLE_CLIENT_ID`; the server checks the token's `aud` against it |
| `VITE_GOOGLE_CLIENT_ID` | unset → dev sign-in | Frontend, **build-time**. `web/.env.local` locally |
| `DJANGO_SECRET_KEY` | dev-only value | **Required** when `DJANGO_DEBUG` is off; startup refuses the default |
| `DJANGO_DEBUG` | on locally, off when `RENDER_EXTERNAL_HOSTNAME` is set | |
| `CONN_MAX_AGE` | 600 s | Connection reuse; Render runs one long-lived process |
| `MAX_UPLOAD_BYTES` | 100 MB | |

`ALLOW_DEV_LOGIN` is computed as `DEBUG and ...`, so the email-only sign-in cannot be switched
on in a deployed environment even by setting the variable.

## Deploying

1. **Google** — create an OAuth client id and add your `*.onrender.com` domain to the
   authorized JavaScript origins.
2. **Render** — *New → Blueprint*, point it at this repo. `render.yaml` declares a free
   Postgres database and one web service. The web service runs `scripts/render-build.sh`
   (installs both halves, builds the SPA, collects static, migrates) and starts gunicorn;
   `DATABASE_URL` is wired to the database automatically. Fill in the variables still marked
   `sync: false` — `GOOGLE_CLIENT_ID` and `VITE_GOOGLE_CLIENT_ID` — the latter is baked into the
   bundle **at build time** by Vite, so changing it later needs a fresh deploy, not just a
   restart.

Migrations run in the build step, so a broken migration fails the deploy instead of half-
breaking a running instance. To run them by hand against the Render database, grab its
connection string from the Render dashboard:

```bash
DATABASE_URL='postgres://...' .venv/bin/python api/manage.py migrate
```

### Things that will bite you

- **Render's free web service sleeps after ~15 minutes idle**, and the next request waits
  roughly 50 seconds for a cold start. It looks hung. Warm it before showing anyone.
- **Render's free Postgres database expires 90 days after creation** and cannot be revived —
  you'd need to create a new one and point `DATABASE_URL` at it. Fine for a takehome, not for
  anything long-lived.
- **Uploaded PDFs do not survive a deploy or restart** on the free plan — there is no persistent
  disk attached. Re-upload after any redeploy before a demo.

## Known gaps

Deliberately out of scope for v1, per PRD §11: burning redactions into output PDFs, OCR over
capture boxes, sharing between users, several PDFs in one folder, moving or resizing an
existing rectangle (v1 is draw and delete), zoom and pan, and touch drawing.

One piece of housekeeping is not built: if a browser uploads bytes and then never registers the
file, the object is stranded on disk. A periodic sweep should delete objects under
`.localstorage/users/` with no matching `Project.storage_path` and an age over 24 hours.
