# bonitabluehair.com

Can Bonita Bluehair hit level 60 in WoW: Forever before Christmas? This site keeps score.

- **Site:** `index.html` reads `data/history.json` and draws everything in the browser.
- **Updates:** `.github/workflows/update.yml` runs every two hours. It calls `scripts/update.py`, which reads the character from the WoW Forever Armory (through classicarmory.gg), records level snapshots, saves a new character frame to `renders/` whenever the model or gear changes, commits, and redeploys GitHub Pages.
- **Run an update now:** Actions tab → "Update tracker and deploy" → Run workflow.
- **Live XP (optional):** `kit/` holds the XPReport addon (level and XP only) and the XP uploader. The uploader posts `live.json` to the separate `TwinkieSlamer/bonitabluehair-live` repo whenever WoW saves (logout or /reload), and the race page reads it from there. The Armory stays the referee: if a later Armory logout shows a lower level than the addon claimed, the page ignores the addon. Download for players: `downloads/xpreport-kit.zip`.
- **The vote ("Does he make it?"):** the race page reads and saves calls through a small Cloudflare Worker in `votes-worker/`, at https://bonita-votes.votes-worker.workers.dev, backed by a D1 database. Names are optional. The server stamps each call with his level from this site's data, closes voting at 60 or Christmas, and caps new votes at 20 per network per day. Redeploy with `npx wrangler@4.152.0 deploy` from that folder; test locally with `wrangler dev --port 8787` and open the page at `http://localhost:8765/?votes=local`.
- **Change the deadline:** edit `deadline` in `data/history.json` (ISO time, UTC). It's set to midnight Eastern on Dec 25.

Pace math uses the Classic XP table, with play time per level estimated as XP ÷ (45 + 5 × level).
