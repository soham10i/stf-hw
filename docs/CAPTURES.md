# Inspection-camera photos

The sorting line has a monocular camera inside its colour hood, 40 mm before the colour sensor. Its
mount, lens and trigger are proven against the model in `stf-cad/hbw/vision/mount.py`. In the 3D twin,
the camera photographs every baked cookie at the moment the cookie passes under the lens:

1. The scene is rendered off screen from the camera's own pose and lens (`web/src/vision/photo.ts`).
   The photo is 256 × 256 px, looks straight down at the belt, and is lit by the ring light's flash.
2. The photo is posted to the API, which validates it and stores it (`services/api/captures.py`).
3. The dashboard's **Vision QC** page shows the newest photos under **Photos from the camera**.

## API

| Route | What it does |
|---|---|
| `POST /vision/captures?flavour=chocolate&n=3&source=twin` | Stores one photo. The body is the JPEG (`Content-Type: image/jpeg`). |
| `GET /vision/captures?limit=48` | Returns the guest's newest photos' records: `id`, `t`, `flavour`, `n`, `source`, `bytes`, `w`, `h`. |
| `GET /vision/captures/{id}.jpg` | Returns one of the guest's photos. |

Each photo belongs to the guest whose twin took it ([DATABASE.md](DATABASE.md)): a visitor sees and opens
only their own. A table made before guests existed needs the column:
`alter table public.captures add column owner text not null default '';
create index captures_owner on public.captures (owner, t desc);`

Uploads come from visitors' browsers, so every upload is checked:

- the request comes from the app's own origin;
- the body is a real JPEG between 32 and 1024 px and at most 200 kB;
- the flavour is a known one;
- a client may send at most a burst of 4 photos, then one every 3 s;
- the server accepts at most `STF_CAPTURE_DAILY` photos a day (default 500).

## Where the photos are stored

| Store | When it is used | Notes |
|---|---|---|
| Local disk | By default | `STF_DATA_DIR/captures/<id>.jpg` and `<id>.json`. The oldest photos are pruned past `STF_CAPTURE_KEEP` (default 2000). On Render's free tier the disk is wiped at every deploy. |
| Supabase | When `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are set | The JPEGs go in a **private** Storage bucket and the records in a Postgres table. Free tier; the photos survive deploys. |

Set `STF_CAPTURES=0` to turn photo capture off.

## Setting up Supabase (free)

1. Create a project at [supabase.com](https://supabase.com).
2. Go to **Storage → New bucket**, name it `captures`, and leave **Public** off.
3. In the **SQL editor**, run:

   ```sql
   create table public.captures (
     id      text primary key,
     t       double precision not null,
     flavour text not null check (flavour in ('chocolate', 'strawberry', 'vanilla')),
     n       integer not null default 0,
     source  text not null default 'twin',
     bytes   integer not null,
     w       integer not null,
     h       integer not null,
     owner   text not null default ''        -- the guest who took it (docs/DATABASE.md)
   );
   create index captures_t on public.captures (t desc);
   create index captures_owner on public.captures (owner, t desc);
   -- row-level security on and no policies: only the server's service key can read or write
   alter table public.captures enable row level security;
   ```

4. Go to **Project Settings → API keys** and copy the project URL and the service key (`service_role`).
   If Storage answers 401 with a new-style secret key, use the legacy `service_role` key.
5. Add `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` to the server's environment: Render's **Environment**
   page, or the git-ignored `.env` locally. **Never put the service key in git or in the browser.** It
   bypasses row-level security. In this setup only the API server holds it, and visitors reach the
   photos only through the API.

Free-tier limits change over time; check Supabase's pricing page. A free project is paused after about
a week without activity, and a request to the dashboard wakes it.
