# Job board status API

A single serverless function that lets `board.html` record job status from any
device. The board is a static page on GitHub Pages and cannot write to a
database; this is the write endpoint.

Storage is one Redis hash, `jobboard:status`, holding `{ref: status}`. Only
non-default statuses are stored, so it stays tiny.

## Deploy (new Vercel project, same account)

1. **vercel.com → Add New → Project** → import `sanjayjainmd/job-search-bot`
2. **Root Directory**: set to **`vercel`** — this is the important one. Without
   it Vercel looks at the repo root, finds Python, and builds the wrong thing.
3. Framework preset: **Other**. No build command, no output directory.
4. **Deploy**

## Connect Redis

In the new project: **Storage → Connect Store → Upstash Redis** (create one if
needed). Vercel injects `KV_REST_API_URL` and `KV_REST_API_TOKEN`
automatically. The function also accepts `UPSTASH_REDIS_REST_URL` /
`UPSTASH_REDIS_REST_TOKEN` if you wire Upstash directly instead.

## Environment variables

**Settings → Environment Variables**, applied to Production:

| Name | Value |
|---|---|
| `BOARD_KEY` | A long random string you invent. The board asks for it once per device and remembers it. |
| `ALLOWED_ORIGIN` | `https://sanjayjainmd.github.io` — restricts which page may call this. Use `*` only while testing. |

Redeploy after adding variables; Vercel does not apply them to an existing
deployment.

## Verify

```
curl -s https://<project>.vercel.app/api/status -H "x-board-key: <BOARD_KEY>"
```

`{}` is the correct empty response. `401` means the key does not match; `500`
means the Redis variables are missing or the project was deployed before they
were set.

Then put the deployment URL into `board.status_api` in `config.yaml`, commit,
and push — the next run bakes it into the board.

## Notes

- The endpoint is guarded by a shared key, not real auth. The data is public
  job listings plus your own marks; the key exists so strangers who find the
  URL cannot rewrite them.
- Status lives here, not in `jobs.db`. The database remains the record of what
  was *sent*; this is your reading state on top of it. `mark.py` still writes
  to the database for anything you want recorded there.
