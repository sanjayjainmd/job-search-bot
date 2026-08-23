// Short entry point for the board.
//
// Typing the full board URL with a key on the end is not realistic on a phone:
//   sanjayjainmd.github.io/job-board/?key=f82ae43e6531...   (77 characters)
//
// This makes the Vercel host itself the entry point, so setting up a device is
// just the bare domain. It redirects to the board with the key attached, and
// the board consumes the key and strips it from the address bar on arrival.
//
// Env vars: BOARD_URL (where the board is published) and BOARD_KEY.

export default function handler(req, res) {
  const board = process.env.BOARD_URL;
  const key = process.env.BOARD_KEY;

  if (!board) {
    return res
      .status(500)
      .send("BOARD_URL is not set in this Vercel project's environment variables.");
  }
  if (!key) {
    return res
      .status(500)
      .send("BOARD_KEY is not set in this Vercel project's environment variables.");
  }

  const target = `${board}${board.includes("?") ? "&" : "?"}key=${encodeURIComponent(key)}`;

  // 302 rather than 301: a permanent redirect gets cached by the browser, which
  // would make a later BOARD_KEY rotation invisible until the cache expires.
  res.setHeader("Cache-Control", "no-store");
  res.redirect(302, target);
}
