// Cross-device job status for board.html.
//
// The board is a static page on GitHub Pages, so it cannot write to a database.
// This function is the write endpoint: the board GETs all statuses on load and
// POSTs one on tap, from a phone or either laptop, and they stay in sync.
//
// Storage is a single Redis hash, {ref: status}. Small by construction - one
// short field per job - so it never needs pagination or cleanup.
//
// Env vars (set in the Vercel project):
//   KV_REST_API_URL   / KV_REST_API_TOKEN     <- Vercel's Upstash integration
//   UPSTASH_REDIS_REST_URL / ..._REST_TOKEN   <- direct Upstash naming
//   BOARD_KEY                                 <- shared secret the board sends
//   ALLOWED_ORIGIN                            <- e.g. https://you.github.io

const REDIS_URL = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
const REDIS_TOKEN = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
const BOARD_KEY = process.env.BOARD_KEY;
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || "*";

const HASH = "jobboard:status";
const STATUSES = new Set(["new", "seen", "applied", "dismissed"]);

async function redis(command) {
  const resp = await fetch(REDIS_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${REDIS_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(command),
  });
  const data = await resp.json();
  if (data.error) throw new Error(data.error);
  return data.result;
}

function cors(res) {
  res.setHeader("Access-Control-Allow-Origin", ALLOWED_ORIGIN);
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Board-Key");
  res.setHeader("Cache-Control", "no-store");
}

export default async function handler(req, res) {
  cors(res);
  if (req.method === "OPTIONS") return res.status(204).end();

  if (!REDIS_URL || !REDIS_TOKEN) {
    return res.status(500).json({ error: "Redis env vars not configured" });
  }
  if (!BOARD_KEY) {
    return res.status(500).json({ error: "BOARD_KEY not configured" });
  }
  // Constant-ish comparison; the payload is job listings, not credentials, but
  // an unguarded endpoint would let anyone rewrite the marks.
  if (req.headers["x-board-key"] !== BOARD_KEY) {
    return res.status(401).json({ error: "bad or missing key" });
  }

  try {
    if (req.method === "GET") {
      // Upstash returns HGETALL as a flat [field, value, field, value, ...].
      const flat = (await redis(["HGETALL", HASH])) || [];
      const out = {};
      for (let i = 0; i < flat.length; i += 2) out[flat[i]] = flat[i + 1];
      return res.status(200).json(out);
    }

    if (req.method === "POST") {
      const body =
        typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};
      const { ref, status } = body;

      if (typeof ref !== "string" || !/^[0-9a-f]{8}$/.test(ref)) {
        return res.status(400).json({ error: "ref must be 8 hex characters" });
      }
      if (!STATUSES.has(status)) {
        return res
          .status(400)
          .json({ error: `status must be one of ${[...STATUSES].join(", ")}` });
      }

      // "new" is the default, so store nothing rather than accumulating noise.
      if (status === "new") await redis(["HDEL", HASH, ref]);
      else await redis(["HSET", HASH, ref, status]);

      return res.status(200).json({ ok: true, ref, status });
    }

    return res.status(405).json({ error: "method not allowed" });
  } catch (err) {
    return res.status(502).json({ error: String(err.message || err) });
  }
}
