# PRD — Construction Drawing Annotator

**Status:** Draft for review — rev. 5
**Author:** jialongclu@gmail.com
**Date:** 2026-09-10
**Stack:** React + TypeScript (Vite) · Django + Django REST Framework · Render (Postgres + web service, free) · Supabase (reserved for a future Auth integration; not used yet)

**Changes in rev. 5:** database and storage moved off Supabase onto Render — a Render-managed
Postgres database (declared in `render.yaml`, wired via `DATABASE_URL`) replaces Supabase
Postgres, and on-disk storage served by Django itself replaces Supabase Storage. Supabase is no
longer used anywhere in this repo; it is reserved for a possible future Auth integration only.
The trade-off: Render's free plan has no persistent disk, so uploaded PDFs do not survive a
deploy or restart (§10, §11), and Render's free Postgres expires after 90 days.

**Changes in rev. 4:** hosting moved from Vercel to **Render**, which collapses the deployment
to one web service serving both halves (§10) and removes the request-body cap that shaped the
upload flow (§9.4). Selecting a rectangle now opens a **delete popover** that removes it
immediately through a new `DELETE` endpoint (§5.2, §9.5) — the one deliberate exception to
save-on-demand, discussed in §9.5.

**Changes in rev. 3:** `DrawingFile` is gone. A project owns one PDF, `Drawing` is reduced to
three fields, and two denormalized columns that could drift were deleted (§7.1). The upload
flow collapsed from four calls to two as a result (§9.4).

**Changes in rev. 2:** storage and database consolidated onto Supabase; DRF confirmed as the
API layer; API surface revised against the proposed endpoint shape (§9.1).

---

## 1. Problem & Goal

Construction teams receive drawing sets as multi-page PDFs. Before those drawings can be
shared or fed into downstream tooling, someone has to mark up each sheet: hide content that
must not leave the org, and mark regions whose text should be extracted.

**Goal:** a web app where a user signs in with Google, uploads a multi-page drawing PDF into a
project folder, flips through sheets with the keyboard, draws **red (block)** and **green
(capture)** rectangles on any sheet, and persists the whole set of annotations with one
explicit **Save**. Clicking a rectangle offers to delete it, which takes effect immediately
(§9.5) — the one action that does not wait for Save.

**Non-goal for v1:** actually performing the redaction or running OCR. We store the geometry
and intent. Burning pixels and extracting text are downstream features (see §11).

---

## 2. Resolved Ambiguities

| Ambiguity | Resolution |
| --- | --- |
| "Move between the **PDF files**" vs. "counter shows which **PDF page** I am on" | **A drawing = one page of the PDF.** A project holds an ordered list of drawings, one per page. ←/→ walks that list and the counter reads `Sheet 7 of 42`. This satisfies both readings with one navigation model and gives every sheet the unique `drawing_id` the brief asks for. |
| "The added drawings should be stored in a folder that users can click" | **Folder = Project.** The dashboard lists project folders; clicking one opens the viewer. |
| How many PDFs per folder? | **One.** Each upload creates its own folder. See §7.1 for why, and for what changes if you want many. |

---

## 3. Users & Scope

- **Primary user:** an authenticated individual working through their own drawing sets.
- **Isolation is a hard requirement.** No user may read another user's PDFs, projects, or
  annotations — including by guessing a URL. See §8.
- **No sharing, no teams, no roles in v1.** Every object has exactly one owner.

---

## 4. User Stories

1. As a visitor, I land on a sign-in screen and authenticate with my Google account.
2. As a new user with no drawings, I see a centered empty state with a single primary button
   prompting me to add drawings.
3. As a user, I upload a multi-page PDF and it becomes a clickable project folder.
4. As a returning user, the **Add drawings** button now sits in the top-right of the header,
   not in the middle of the page.
5. As a user, I open a folder and see the first sheet rendered, with a `Sheet 1 of N` counter
   at the top.
6. As a user, I press **→** / **←** — or click **Prev** / **Next** — to move between sheets.
7. As a user, I click and drag to draw a **red** rectangle over content to block.
8. As a user, I click and drag to draw a **green** rectangle over text to capture.
9. As a user, I click an existing rectangle, a **Delete** button appears next to it, and
    clicking that button removes the rectangle.
10. As a user, my annotations are **not** written to the database until I click **Save** — with
    the single, deliberate exception of that Delete button (§9.5).
11. As a user, if I try to leave with unsaved work, I'm warned.
12. As a user, I reopen the project days later and every rectangle is exactly where I left it.

---

## 5. UX Specification

### 5.1 Screens

**Sign in.** Product name, one-line description, Google sign-in button. Nothing else.

**Dashboard — empty state.** Vertically and horizontally centered: an icon, the line "No
drawings yet", and a primary button **Add drawings**. No header button in this state.

**Dashboard — populated.** Header with product name on the left and **Add drawings** on the
right. Body is a grid of folder cards showing name, sheet count, and relative last-modified
time. Clicking a card opens the viewer.

**Viewer.**

```
┌──────────────────────────────────────────────────────────────────────┐
│ ← Back   A-101.pdf                          [● Block] [● Capture]    │  toolbar
│          Sheet 7 of 42                      [Undo]  [Save •]         │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [ ‹ ]                 rendered PDF page                     [ › ]   │  canvas
│                     + annotation overlay                             │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

- The counter `Sheet 7 of 42` is the top-center element, always visible.
- Tool toggle is a two-state segmented control: **Block (red)** / **Capture (green)**.
- **Save** shows a dot when there are unsaved changes and is disabled when clean.
- Prev/Next are large hit targets pinned to the canvas edges, disabled at the ends.

### 5.2 Selecting a rectangle, and deleting it

Clicking an existing rectangle selects it: a dashed outline appears around it and a small
**popover** opens directly above it, naming the kind and offering one action.

```
        ┌──────────────────┐
        │ Block   [Delete] │   ← popover, anchored to the rectangle
        └────────┬─────────┘
   ┌─────────────▼─────────────┐
   │▒▒▒▒▒ selected rectangle ▒▒│   ← dashed selection outline
   └───────────────────────────┘
```

- The popover is centred on the rectangle and clamped inside the page, so a rectangle against
  an edge still gets a reachable button. If the rectangle is near the top of the sheet, the
  popover flips below it.
- The Delete button takes focus when the popover opens, so <kbd>Enter</kbd> confirms and
  <kbd>Esc</kbd> dismisses without touching the mouse.
- While the request is in flight the button reads **Deleting…** and is disabled, so an
  impatient double-click cannot fire twice.
- Clicking bare paper, pressing <kbd>Esc</kbd>, or changing sheet closes it.

Clicking Delete removes the rectangle **immediately** — see §9.5 for the endpoint and for why
this one action does not wait for Save.

### 5.3 Interaction rules

| Input | Behavior |
| --- | --- |
| `→` / `↓` / `PageDown` | Next sheet |
| `←` / `↑` / `PageUp` | Previous sheet |
| `1` / `2` | Select Block / Capture tool |
| Click a rectangle | Select it and open the delete popover |
| Click bare paper | Deselect |
| `Cmd/Ctrl+Z` | Undo last annotation change on the current project |
| `Delete` / `Backspace` | Delete selected rectangle (same path as the popover button) |
| `Cmd/Ctrl+S` | Save |
| `Esc` | Deselect / cancel an in-progress drag |

Handlers attach at the document level in the viewer only, and are suppressed while focus is
in an input or a modal is open. Navigation does **not** wrap at the ends.

**Drawing:** mousedown starts a rubber-band rect, mousemove previews live, mouseup commits.
Drags under 6px in either dimension are discarded as accidental clicks. Rectangles are clamped
to the page bounds. Block `#EF4444`, capture `#22C55E`, both at ~30% fill with a solid 2px
stroke so the drawing underneath stays readable.

**Save:** edits accumulate in client state. Save issues one request for the entire project,
shows a spinner, then a brief "Saved" confirmation. `beforeunload` and an in-app route guard
warn on unsaved changes.

### 5.4 Accessibility

Prev/Next are real `<button>`s with `aria-label`s; the counter is an `aria-live="polite"`
region; the tool toggle is a labeled radio group; focus rings are visible. The delete popover
is a labeled `role="dialog"` whose button receives focus on open, so a selected rectangle can
be deleted from the keyboard alone. The drawing surface itself is mouse/trackpad-only in v1 —
a documented limitation.

---

## 6. Architecture

```
Browser (React SPA)
  │  fetch, credentials: include
  ▼
Render — one web service (gunicorn)              Render — managed Postgres
  ├── /*           → built SPA, served by WhiteNoise   (web/dist)
  └── /api/*       → Django + DRF                      (api/)
                        │
                        ├── Render Postgres (separate managed resource, via DATABASE_URL)
                        └── on-disk storage (this process, signed URLs)
                                  ▲
                                  └── client PUTs the PDF directly, on a
                                      server-issued signed upload URL
```

Both halves ship as **one Render web service**: gunicorn runs Django, and WhiteNoise serves the
Vite build from the same process. Splitting the frontend onto a Render Static Site was the
obvious alternative and is the wrong call here — it would put the SPA on a different origin
from the API, forcing the refresh cookie to `SameSite=None` and dragging CORS into the login
path. One origin keeps the cookie `SameSite=Strict; Secure; HttpOnly` and needs no CORS at all.

The database is a second Render-managed resource declared alongside the web service in
`render.yaml`; Render wires its connection string into `DATABASE_URL` automatically.

The PDF upload still bypasses the main DRF view, going browser → a dedicated signed-URL storage
endpoint that Django mints (§9.4) — the same process handles it, since storage is local disk
rather than a separate object store.

### 6.1 Repo layout

```
provision-takehome/
├── web/                     Vite + React + TS
│   ├── src/
│   │   ├── routes/          SignIn, Dashboard, Viewer
│   │   ├── features/
│   │   │   ├── auth/
│   │   │   ├── projects/
│   │   │   └── annotations/ store, overlay canvas, hit-testing
│   │   ├── lib/             api client, pdf.js worker setup
│   │   └── types/           generated from DRF serializers
├── api/
│   ├── config/              settings, urls (incl. SPA fallback), wsgi
│   ├── accounts/            User, Google verification, JWTs
│   └── drawings/
│       ├── models.py        Project, Drawing, Annotation
│       ├── serializers.py
│       ├── views.py         ProjectViewSet
│       ├── permissions.py   IsOwner
│       ├── storage.py       on-disk storage backend
│       └── urls.py          DefaultRouter
├── scripts/
│   ├── render-build.sh      install, build SPA, collectstatic, migrate
│   └── make_sample_pdf.py
├── render.yaml
└── PRD.md
```

### 6.2 Key frontend choices

- **PDF rendering:** `pdfjs-dist` driven directly (not `react-pdf`) so we control the canvas
  and can read the exact rendered viewport for coordinate math. Worker bundled, not from CDN.
- **Two canvases:** one for the PDF page, one absolutely positioned above it for annotations,
  sharing a CSS box. Redrawing the overlay during a drag never re-renders the PDF.
- **Prefetch:** sheets N±1 render into a bounded offscreen cache (~5 pages) so ←/→ is instant.
  Because a project is one PDF, the whole document is fetched once and every sheet renders from
  the same in-memory `PDFDocumentProxy` — no per-sheet network round trip at all.
- **State:** a Zustand store holding `annotationsByDrawingId`, a `dirty` flag, and an undo
  stack — the single source of truth between load and save.

### 6.3 Coordinate system

Annotations are stored as **normalized floats in `[0,1]`** relative to the unrotated PDF page
box: `{x, y, w, h}`, origin top-left. Screen pixels are never persisted. This keeps annotations
correct at any zoom level, window size, or device pixel ratio, and is the single most important
decision behind "the rectangle is exactly where I left it".

---

## 7. Data Model

Three tables plus `User`.

```python
class User(AbstractBaseUser):
    id           = UUIDField(primary_key=True)
    email        = EmailField(unique=True)
    google_sub   = CharField(unique=True, db_index=True)   # stable Google subject id
    display_name = CharField(blank=True)
    picture_url  = URLField(blank=True)
    created_at   = DateTimeField(auto_now_add=True)

class Project(Model):                    # the "folder" — and the PDF it holds
    id           = UUIDField(primary_key=True)      # client may supply — see §9.2
    owner        = FK(User, on_delete=CASCADE, related_name="projects")
    name         = CharField(max_length=200)        # defaults to the filename
    filename     = CharField(max_length=255)        # as uploaded, for display
    storage_path = CharField(max_length=512)        # key under the on-disk storage root
    size_bytes   = BigIntegerField()
    created_at   = DateTimeField(auto_now_add=True)
    updated_at   = DateTimeField(auto_now=True)

class Drawing(Model):                    # one sheet — the unique drawing_id the brief asks for
    id          = UUIDField(primary_key=True)
    project     = FK(Project, on_delete=CASCADE, related_name="drawings")
    page_number = PositiveIntegerField()            # 1-based
    class Meta:
        unique_together = [("project", "page_number")]
        ordering = ["page_number"]

class Annotation(Model):
    class Kind(TextChoices):
        BLOCK   = "block"     # red
        CAPTURE = "capture"   # green
    id         = UUIDField(primary_key=True)      # client-generated → idempotent save
    drawing    = FK(Drawing, on_delete=CASCADE, related_name="annotations")
    kind       = CharField(choices=Kind.choices)
    x, y, w, h = FloatField() * 4                 # normalized [0,1]
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    class Meta:
        indexes     = [Index(fields=["drawing", "kind"])]
        constraints = [CheckConstraint(...)]      # 0 ≤ x,y ≤ 1; 0 < w,h ≤ 1
```

`Project.owner` is the only place ownership is stored, and every query is scoped through it.
There is no code path that fetches a Drawing or Annotation without joining back to
`owner=request.user`.

### 7.1 Why `DrawingFile` was removed

The previous revision had a fourth table sitting between `Project` and `Drawing`, holding the
filename, the storage path, and the page count. It existed for exactly one reason: to let a
project hold **more than one PDF** without repeating the file's storage path on all 42 of its
sheet rows.

That is the whole justification. Once a project holds one PDF, the table has nothing left to
own — its fields belong on `Project`, and it is pure overhead: an extra join on the bootstrap
query, an extra serializer, an extra level of nesting in the response, and an extra hop for
every ownership check to traverse.

**So: one PDF per folder, and the table is gone.** Each upload creates its own folder, which
matches a dashboard whose primary object is a grid of clickable folders.

Three fields died with it, and two of them were latent bugs rather than merely redundant:

| Removed | Why |
| --- | --- |
| `DrawingFile.page_count` | Derivable. We create exactly one Drawing per page, so `project.drawings.count()` *is* the page count. A stored copy can only ever disagree with the rows it describes |
| `DrawingFile.order_index` | Only existed to order multiple files within a project. With one file there is no ordering problem to solve |
| `Drawing.order_index` | **This one was a bug.** It was a project-global position, computed at upload as `drawings.count() + i`, under a `unique_together("project", "order_index")`. Delete a 10-page file from a 42-sheet project and the count drops to 32, so the next upload starts numbering at 32 — colliding with rows 32–41 that still exist, and raising an `IntegrityError` on a perfectly ordinary sequence of user actions. With one PDF per project, `page_number` is already the position and the field is unnecessary |

`Drawing` is now three fields: an id, its project, and which page it is. That is genuinely all
a sheet is.

### 7.2 What changes if you want many PDFs per folder

If a folder should accept repeated uploads, `DrawingFile` comes back — that is the right shape
for it, and denormalizing `storage_path` onto every Drawing instead would be worse. Nothing
else in this document changes:

- Move `filename`, `storage_path`, `size_bytes` off `Project` onto a new `DrawingFile`.
- Give `Drawing` a `file` FK, and order by `("file__uploaded_at", "page_number")`.
- `POST /api/projects/` splits back into create-then-attach (§9.4).

That is a mechanical migration of maybe thirty lines, plus a backfill of one `DrawingFile` row
per existing project. It is not a rewrite, so starting with the simpler shape costs little if
the requirement changes.

The third option — splitting the PDF into one file per page at upload, so `storage_path` could
honestly live on `Drawing` — is not worth it. It needs `pdf-lib` in the browser, turns one
upload into N, re-uploads a lot of bytes, and loses the original document. Rejected.

---

## 8. Authentication & Isolation

**Flow.** Google Identity Services renders the sign-in button and returns an **ID token** →
`POST /api/auth/google/` → Django verifies signature, `aud`, `iss`, and expiry with
`google-auth` → `get_or_create` by `google_sub` → server returns a short-lived access JWT (15
min, held in memory) and sets a long-lived refresh JWT as an HttpOnly cookie (30 days). The SPA
refreshes transparently on 401.

I chose raw ID-token verification over `django-allauth` because allauth's session/redirect flow
assumes server-rendered pages and a writable session store — awkward on serverless, and we'd
use maybe 5% of the library.

### 8.1 Storage has no authorization system of its own

**Django is the sole authority on who may read what.** There is no separate authorization layer
on top of the on-disk storage backend — every signed URL Django issues is generated per-request
after `project.owner == request.user` is checked, and nothing is reachable without one.

- Objects live under `api/.localstorage`, outside `STATIC_ROOT` and never served directly;
  every read or write goes through a dedicated endpoint that validates an HMAC-signed, expiring
  token first.
- Object paths are namespaced `users/{user_id}/{file_id}.pdf`, so a path carries its own
  ownership claim that Django re-checks on every request.

**Reading a sheet.** The SPA calls `GET /api/projects/{id}/source/`. Django checks
`project.owner == request.user`, then returns a **signed read URL with a ~5 minute TTL** against
its own storage endpoint. The client never holds a durable file URL, and a leaked one expires on
its own. Because a project is one PDF, this is called once per project open, not once per sheet.

**Writing a file.** Same shape in reverse — Django mints a **signed upload URL** scoped to one
path it chose (§9.4). The client cannot pick where the bytes land.

**Everything else.** A DRF `IsOwner` permission asserts ownership on every object, and
`get_queryset` filters every list by owner. A cross-user request returns **404**, not 403, so
IDs can't be enumerated.

---

## 9. API

Django REST Framework throughout: `ModelViewSet`s registered on a `DefaultRouter`, model
serializers, `IsAuthenticated + IsOwner` as the default permission classes, and
`@action`-decorated routes for the operations that aren't plain CRUD.

### 9.1 Revision note — the proposed endpoint shape

The three endpoints proposed in review, and what shipped instead:

| Proposed | Assessment | Ships as |
| --- | --- | --- |
| `GET /project/{projectId}` → list of drawings | **Right, and kept.** One request to open a folder. Widened to include annotations, so the viewer needs exactly one round trip | `GET /api/projects/{id}/` |
| `POST /project` `{projectId, [drawingIds]}` | **Mostly kept, after rev. 3.** Client-supplied `projectId` makes create idempotent — a retried request can't produce two folders. The instinct that this call should also create the drawings was right; it just needs a *page count* rather than a list of ids, since the ids don't exist yet and a Drawing can't precede the Project it points at | `POST /api/projects/` `{id, name, storage_path, page_count}` — creates the folder and all N drawings in one transaction |
| `POST /drawing` `{drawingId, drawingPDF, annotations}` | **Replaced.** Four problems — see below | `POST /api/upload-ticket/` for the bytes, `PUT /api/projects/{id}/annotations/` for the markup |
| *(rev. 4)* "delete the annotation via `DELETE /projects/{id}`" | **Redirected.** That route already exists and deletes **the entire folder** — every sheet and every annotation in it, plus the PDF. Wiring the popover's Delete button to it would destroy a whole drawing set on a click meant to remove one rectangle. The annotation id has to be in the path | `DELETE /api/projects/{id}/annotations/{annotationId}/` (§9.5) |

Why `POST /drawing` can't carry the PDF:

1. **Base64 in a JSON body is the wrong shape for a large file.** It inflates the payload ~33%,
   buffers the whole thing in memory on both ends, and gives up resumability and progress. On
   Vercel this was fatal — a hard 4.5 MB body cap. Render has no such cap (rev. 4), so this
   drops from *impossible* to *bad*, and the direct-to-storage upload stands on its own merits.
2. **One PDF is many drawings.** Under §2, a 42-page upload produces 42 drawings. An endpoint
   named `/drawing` that accepts a whole PDF conflates the file with the sheet, and leaves
   unanswered who assigns the other 41 drawing IDs.
3. **It couples upload to save.** Annotations change constantly; the PDF never changes after
   upload. Sharing one endpoint means either re-sending the PDF on every save, or an endpoint
   with two modes and a half-ignored payload.
4. **Per-drawing saves aren't atomic.** The brief asks to save *the folder*. One request per
   drawing means N requests, and a failure at request 30 of 42 leaves the folder half-saved
   with no clean way to recover. One bulk request in one transaction either lands or doesn't.

### 9.2 Endpoints

All routes under `/api/`, JSON, authenticated unless noted.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/google/` | Exchange Google ID token for a session *(public)* |
| `POST` | `/auth/refresh/` | New access token from refresh cookie *(public)* |
| `POST` | `/auth/logout/` | Clear refresh cookie |
| `GET` | `/me/` | Current user |
| `POST` | `/upload-ticket/` | Mint a signed upload URL in this user's namespace |
| `GET` | `/projects/` | List the user's folders — name, sheet count, `updated_at` |
| `POST` | `/projects/` | Create a folder **and** its drawings from an uploaded PDF |
| `GET` | `/projects/{id}/` | **Viewer bootstrap** — project + ordered drawings + all annotations |
| `PATCH` | `/projects/{id}/` | Rename a folder |
| `DELETE` | `/projects/{id}/` | Delete folder, drawings, annotations, and the stored object |
| `GET` | `/projects/{id}/source/` | Short-lived signed read URL for the project's PDF |
| `PUT` | `/projects/{id}/annotations/` | **The Save button.** Bulk replace, one transaction |
| `DELETE` | `/projects/{id}/annotations/{annotationId}/` | **The popover's Delete button.** Removes one rectangle now |

Eleven endpoints, and every one that touches drawings is **nested under its project**. That's
not cosmetic: ownership is checked once, structurally, when the router resolves the project —
rather than each handler remembering to re-derive the owner from a bare drawing ID.

`GET /api/projects/{id}/` returns:

```jsonc
{
  "id": "…", "name": "Level 2 Redlines", "filename": "A-101.pdf",
  "page_count": 42, "updated_at": "…",
  "drawings": [
    { "id": "…", "page_number": 1,
      "annotations": [ { "id": "…", "kind": "block", "x": 0.11, "y": 0.24, "w": 0.30, "h": 0.08 } ] }
  ]
}
```

`page_count` is a serializer field (`drawings.count()`), not a column — the response shape is
unchanged by rev. 3 even though the schema lost a table.

### 9.3 Bulk save

```jsonc
PUT /api/projects/{id}/annotations/
{
  "drawings": [
    { "drawing_id": "…",
      "annotations": [
        { "id": "client-uuid", "kind": "block",   "x": 0.11, "y": 0.24, "w": 0.30, "h": 0.08 },
        { "id": "client-uuid", "kind": "capture", "x": 0.52, "y": 0.61, "w": 0.18, "h": 0.05 }
      ] }
  ]
}
```

Semantics: **full replace, scoped to the drawings named in the payload**, in a single
transaction. Rows in the DB but absent from the payload for those drawings are deleted; rows
with a matching client UUID are updated; new UUIDs are inserted. Because IDs come from the
client, a retried save is idempotent — a dropped response can't duplicate rectangles. Drawings
not mentioned are untouched. Every `drawing_id` is validated against the project *and* the
owner before any write. The response returns the canonical saved state, which the client swaps
in and marks clean.

Implemented as a DRF `@action(detail=True, methods=["put"])` on `ProjectViewSet`, with a
serializer that validates the nested payload before the transaction opens.

### 9.4 Upload path

The PDF never passes through the main DRF views. Render imposes no body cap the way Vercel did,
so keeping the upload off the JSON API code path is no longer forced by a hard limit — it is
kept because it is still the right shape: a 60 MB drawing set would otherwise buffer through the
same request/response cycle that runs serialization and auth, tying up a worker for the whole
transfer. It still lands on this same web service, though, since storage is local disk rather
than an external object store — a genuinely separate storage provider would additionally save
that worker's own bandwidth for the transfer, which this shape does not.

Two API calls, one direct storage PUT:

1. `POST /api/upload-ticket/` with `{filename, size_bytes}`. Django picks the path
   `users/{user_id}/{file_id}.pdf`, signs an upload token, and returns
   `{file_id, storage_path, signed_url, token}`.
2. Client `PUT`s the PDF **directly to the signed storage URL**, bypassing the main API views.
3. Client opens the PDF locally with pdf.js to read `page_count`.
4. `POST /api/projects/` with `{id, name, filename, storage_path, size_bytes, page_count}`.
   Django re-validates that `storage_path` sits in this user's namespace, `HEAD`s the object to
   confirm it exists and matches `size_bytes`, then creates the `Project` and its `page_count`
   `Drawing` rows in **one transaction** — returning the full bootstrap payload so the viewer
   opens with no further request.

The ticket is deliberately *not* nested under a project: the project doesn't exist yet, and
requiring one first would mean creating an empty folder that's orphaned if the upload fails.
Ownership still holds, because the path prefix is the user's namespace and Django chose it.

Client-supplied `page_count` is trusted only as a hint for row creation; it's re-validated on
first render, and a mismatch surfaces as a repairable error rather than corrupt state. This
also keeps `pypdf` off the server entirely.

**Orphaned objects.** If step 2 succeeds and step 4 never happens, the bytes sit in the bucket
with no row pointing at them. A periodic sweep deletes objects under `users/` with no matching
`Project.storage_path` and an age over 24 hours. Not v1-critical, but it's the kind of thing
that quietly eats a free-tier quota, so it's in the README.

### 9.5 Deleting one annotation

```jsonc
DELETE /api/projects/{id}/annotations/{annotationId}/   →   204 No Content
```

**Scoped under its project, not standalone.** Ownership is settled by the router before the
annotation id is even read: resolving the project already restricted us to one this user owns,
and the delete is filtered to drawings inside it. An id belonging to someone else matches
nothing — no leak, and no second ownership check to forget.

**Idempotent.** A rectangle that is already gone returns 204, not 404, so a retry after a
dropped response is not an error and the UI never has to distinguish "deleted" from "deleted
twice". A request against a project the caller does not own is a different matter and returns
**404**, exactly as every other project route does.

#### Why this one action does not wait for Save

This is a deliberate exception to §1's "nothing reaches the database until Save", and it is
worth naming rather than glossing over. The brief asks for the popover's Delete button to hit
an endpoint, which means deletion is immediate while drawing stays buffered. That asymmetry is
defensible — delete is the one destructive action, and making it explicit and instant matches
what a Delete button visibly promises — but it has a consequence worth accepting knowingly:

> **A deleted rectangle cannot be recovered by declining to save.** Undo restores it to the
> buffer and the next Save re-creates it (the bulk save is a full replace, so the id comes
> back); but closing the tab after a delete does not bring it back the way it would for an
> unsaved edit.

The client bridges the two models with one rule: **only rectangles the server already holds are
deleted through the API.** A rectangle drawn and then removed before any save has never existed
server-side, so it is simply dropped from the buffer. Without that distinction every
draw-then-reconsider would fire a DELETE for an id the server has never seen.

| Rectangle's state | Delete does |
| --- | --- |
| Saved (server holds it) | `DELETE` request, then drop from the buffer. Does not by itself make the buffer dirty |
| Drawn but never saved | Drop from the buffer only. No request |

The keyboard <kbd>Delete</kbd> key runs the identical path, so the two ways to remove a
rectangle cannot drift apart.

---

## 10. Deployment

Declared in `render.yaml`, so the whole thing deploys as a Render Blueprint.

| Concern | Decision |
| --- | --- |
| Host | **One Render web service**, free plan. `gunicorn config.wsgi --workers 2 --threads 4`. Not two services — see §6 for why one origin matters |
| Routing | Django owns everything. `/api/*` hits DRF; every other path falls through to the SPA's `index.html` so client-side routes survive a reload |
| Static files | **WhiteNoise** serves the Vite build from the same process, with hashed filenames and long-lived caching. DRF's browsable API is off in production |
| Build | `scripts/render-build.sh` — pip install, `npm ci && npm run build`, `collectstatic`, `migrate` |
| Database | **Render Postgres**, free tier — a second resource declared in `render.yaml`'s `databases:` block, wired into `DATABASE_URL` via `fromDatabase`. A direct connection, no transaction-mode pooler in front of it |
| Connections | `CONN_MAX_AGE=600` with `conn_health_checks=True`. Render runs one long-lived process, so connections are worth reusing — the opposite of the serverless setting, where holding one was the bug |
| Storage | **On-disk**, under `api/.localstorage`, served by Django itself through HMAC-signed URLs. No attached persistent disk on the free plan, so an upload does not survive a deploy or restart (§11 notes the risk) |
| Migrations | In the build step, before any traffic reaches the new instance. A failed migration fails the deploy instead of half-breaking a live one. **Never** at request time |
| Hosts | `ALLOWED_HOSTS` comes from `RENDER_EXTERNAL_HOSTNAME`, not a wildcard |
| Secrets | Render env group: `GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID` (build-time), and a generated `DJANGO_SECRET_KEY`. `DATABASE_URL` is set automatically from the Render database resource, not entered by hand |
| Health check | `/api/health/`, which Render polls |

### 10.1 What moving off Vercel changed

Three of rev. 3's decisions existed only to survive serverless, and two of them reverse:

| Was | Now | Why |
| --- | --- | --- |
| `CONN_MAX_AGE=0` | `600`, with health checks | A persistent process should reuse connections; reopening one per request was pure serverless tax |
| Migrations run separately, never in a deploy | Run in the build step | There is a real build phase now, and it gates the release |
| Direct-to-storage upload was *mandatory* (4.5 MB body cap) | Direct-to-storage upload is *chosen* | The cap is gone; the reasoning in §9.4 stands on its own |

What does **not** change: same-origin SPA and API, the `SameSite=Strict` refresh cookie, and
every line of the isolation model in §8. Database and storage moved off Supabase onto Render in
rev. 5, described above.

---

## 11. Out of Scope for v1

Burning redactions into output PDFs · OCR / text extraction from capture boxes · sharing, teams,
or permissions beyond single-owner · multiple PDFs per folder (§7.2) · moving or resizing an
existing rectangle after it's drawn (v1 is draw + delete) · zoom and pan · non-PDF formats ·
thumbnail sheet navigator · autosave · annotation history or audit log · mobile/touch drawing.

---

## 12. Risks & Open Questions

| # | Item | Impact | Recommendation |
| --- | --- | --- | --- |
| 1 | **Render's free Postgres database expires 90 days after creation** and cannot be revived | A reviewer opening the deployed app months later hits a database that no longer exists | Noted in the README. Recreate the database and repoint `DATABASE_URL` if the deployment outlives 90 days |
| 2 | **No persistent disk on Render's free web service**, so on-disk storage loses every uploaded PDF on deploy or restart | A reviewer sees an empty dashboard or a broken file link after any redeploy | Accepted for this project's scope. Noted in the README; re-upload after a redeploy before a demo. A real deployment would need a paid instance with a disk, or a real object store |
| 3 | **Render's free plan spins the service down after ~15 minutes idle.** The next request pays a cold start of roughly 50 seconds | The first visit after a quiet period looks hung, and this is now the *slower* of the two free-tier wake-ups | Warm it before a demo. If the delay is unacceptable, this is the one thing worth paying for — a paid instance type removes it outright |
| 4 | **Deleting a rectangle is immediate and not undoable by refusing to save** (§9.5) | A misclick on Delete is permanent once the request lands | Accepted, at the brief's request. The popover is small and deliberate rather than a hover affordance, and Undo plus Save restores the rectangle. If this proves too sharp, the fix is a confirm step or a toast with Undo, not a change to the endpoint |
| 5 | **One PDF per folder** is a real constraint, not just a simplification | Repeated uploads make many folders instead of filling one | §7.2 is the reversal path — a ~30-line migration. Confirm the constraint is acceptable before milestone 2 |
| 6 | **Very large drawing sets** (200+ sheets) make the bootstrap payload and bulk save large | Slow open/save | Acceptable at v1 scale. If it bites: paginate drawings and send only dirty sheets — the API shape already permits this |
| 7 | **No PDF was attached to the repo** | Can't validate against the real document | Please drop the sample PDF into the project root; page dimensions and rotation flags in real construction sets are worth testing early |

**Questions:**

1. Confirm one PDF per folder (§7.1). This is the one decision that shapes the schema, and it's
   cheap to reverse but not free.
2. Is draw-and-delete enough for v1, or do you need to move/resize existing rectangles?
3. Is the immediate, non-undoable delete in §9.5 what you want, or should the popover's Delete
   button buffer like every other edit and persist on Save? Both are a few lines apart; the
   endpoint stays either way.

---

## 13. Milestones

| # | Deliverable | Exit criteria |
| --- | --- | --- |
| 0 | Scaffold | Vite+TS and Django both boot; `/api/health/` returns 200 on a deployed Render service |
| 1 | Auth | Google sign-in works end to end; `/api/me/` returns the right user; refresh cookie survives reload |
| 2 | Data layer | Three models, migrations, DRF serializers, `IsOwner`; cross-user access returns 404 (covered by tests); Render Postgres connection verified in a deployed environment |
| 3 | Upload + folders | Empty state → signed upload → folder card appears; button relocates to top-right once a folder exists |
| 4 | Viewer | pdf.js renders sheets from one signed URL; counter, Prev/Next buttons, ←/→ keys, prefetch |
| 5 | Annotations | Red and green rectangles draw and undo; clicking one opens the delete popover and the DELETE endpoint removes it; normalized coordinates verified across window sizes |
| 6 | Save | Bulk PUT persists; reload restores exactly; unsaved-changes guard works |
| 7 | Polish + deploy | Loading and error states, edge cases, production deploy, README |

Testing along the way: `pytest` + DRF's `APIClient` for ownership isolation and bulk-save
semantics — the two places a bug is most costly — and Vitest on the coordinate normalization
math.

---

## 14. Success Criteria

- A second signed-in user cannot read the first user's projects, drawings, annotations, or PDF
  bytes — verified by an automated test, not by inspection.
- No storage or database credential of any kind is reachable from the browser bundle.
- Annotations reload pixel-accurate after a full refresh at a different window size.
- ←/→ advances a rendered sheet in under ~150 ms for a cached neighbor.
- Nothing reaches the database until **Save** is clicked, except a rectangle deleted through
  the popover — which is gone from the database before the button stops spinning, and stays
  gone after a reload.
- Deleting a rectangle never deletes the folder, its sheets, or its other rectangles.
