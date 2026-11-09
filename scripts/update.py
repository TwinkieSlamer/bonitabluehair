#!/usr/bin/env python3
"""Check Bonita Bluehair on the WoW Forever Armory and update the site's data.

Run by GitHub Actions every hour (see .github/workflows/update.yml), or by hand:

    pip install pillow
    python scripts/update.py

What it does:
  * records a level snapshot each time the Armory shows a new logout
  * saves a new gear-reel frame whenever his equipped gear changes, or the
    character render changes (a new look). The Armory redraws the render
    later than it updates the gear, so a gear change is saved right away with
    its last picture, and the picture is swapped in when the Armory catches up
  * keeps the last known professions, reputations and record stats when an
    Armory response comes back without them
  * writes everything to data/history.json, which index.html reads

    python scripts/update.py --min-gap 40   # skip if the last check was under 40 minutes ago
"""
import argparse
import datetime as dt
import email.utils
import hashlib
import http.client
import io
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "history.json"
RENDERS = ROOT / "renders"
API = "https://classicarmory.gg/api/character/us/forever/bonita-bluehair?ns=forever"
ARMORY_PAGE = "https://classicarmory.gg/character/us/forever/bonita-bluehair"
UA = {"User-Agent": "christmas-bet-tracker/1.0 (+https://bonitabluehair.com)"}

SLOT_ORDER = ["head", "neck", "shoulder", "back", "chest", "shirt", "tabard", "wrist", "hands", "waist",
              "legs", "feet", "finger1", "finger2", "trinket1", "trinket2", "mainhand", "offhand", "ranged"]


RETRY_DELAYS = (15, 45, 120)  # seconds to wait before each retry
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 180  # never sit longer than this on one wait, whatever the server asks for


def retry_wait(exc, attempt):
    """Seconds to wait before the next try: the server's Retry-After if it sent one, else the backoff."""
    header = exc.headers.get("Retry-After") if isinstance(exc, urllib.error.HTTPError) else None
    if header:
        try:
            seconds = float(header)
        except ValueError:
            try:
                seconds = (email.utils.parsedate_to_datetime(header) - dt.datetime.now(dt.timezone.utc)).total_seconds()
            except (TypeError, ValueError):
                return RETRY_DELAYS[attempt]
        return min(max(seconds, RETRY_DELAYS[attempt]), MAX_RETRY_AFTER)  # Retry-After is a minimum, not a target
    return RETRY_DELAYS[attempt]


def get(url, accept="*/*"):
    """Fetch a URL, waiting and trying again through rate limits, server errors and dropped connections."""
    req = urllib.request.Request(url, headers={**UA, "Accept": accept})
    retries = len(RETRY_DELAYS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == retries:
                raise
            problem, wait = f"HTTP {exc.code}", retry_wait(exc, attempt)
            exc.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
            if attempt == retries:
                raise urllib.error.URLError(exc) from exc
            problem, wait = str(exc) or type(exc).__name__, retry_wait(exc, attempt)
        print(f"{url}: {problem}. Waiting {wait:.0f}s before retry {attempt + 1} of {retries}.", flush=True)
        time.sleep(wait)


def gear_key(gear):
    """What the race page compares between frames: each item by slot and name."""
    return sorted(f"{g.get('slot')}|{g.get('name')}" for g in gear or [])


def frame_stamp(ts):
    return dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).strftime("%Y%m%d-%H%M")


def gear_list(equipment):
    items = []
    for slot in SLOT_ORDER:
        it = (equipment or {}).get(slot)
        if not it:
            continue
        items.append({
            "slot": it.get("slotLabel") or slot,
            "name": it.get("name"),
            "quality": it.get("quality"),
            "ilvl": it.get("itemLevel"),
        })
    return items


def save_render(png_bytes, stamp, level):
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    box = im.getchannel("A").getbbox()
    if box:
        pad = 24
        im = im.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                      min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
    RENDERS.mkdir(exist_ok=True)
    name = f"{stamp}-l{level}.webp"
    im.save(RENDERS / name, "WEBP", quality=88, method=6)
    im.save(RENDERS / "latest.png", optimize=True)
    # Link previews (Discord, iMessage, texts) get a 1200x630 card of the latest look.
    card = Image.new("RGB", (1200, 630), (10, 15, 30))
    fig = im.copy()
    fig.thumbnail((560, 590))
    card.paste(fig, ((1200 - fig.width) // 2, 630 - fig.height - 20), fig)
    card.save(RENDERS / "og.png", optimize=True)
    return f"renders/{name}", im.size


def checked_recently(data, minutes):
    """True when the last Armory check was less than `minutes` ago."""
    try:
        last = dt.datetime.strptime(data.get("checkedAt", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return False
    return dt.datetime.now(dt.timezone.utc) - last < dt.timedelta(minutes=minutes)


def update_looks(looks, api, ts, level):
    """Add a gear-reel frame when his gear or his render changes. Returns a line for the log."""
    last = looks[-1] if looks else None
    last_gear = (last or {}).get("gear") or []
    gear = gear_list(api.get("equipment"))
    # An empty or much shorter list is a partial Armory response, not him taking his gear off.
    gear_known = bool(gear) and len(gear) >= len(last_gear) // 2
    gear_changed = gear_known and last is not None and gear_key(gear) != gear_key(last_gear)

    png = digest = None
    if api.get("mainRender"):
        try:
            png = get(api["mainRender"], "image/png")
            digest = hashlib.sha256(png).hexdigest()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"Could not fetch the character render ({exc}). Level data still saved.")
    new_render = digest is not None and (last is None or digest != last.get("hash"))

    def picture(frame, t, lvl):
        path, size = save_render(png, frame_stamp(t), lvl)
        frame.update(img=path, w=size[0], h=size[1], hash=digest)
        frame.pop("stalePic", None)

    if last is None:
        if digest is None:
            return "No render yet for a first frame."
        frame = {"t": ts, "level": level, "itemLevel": api.get("itemLevel"), "gear": gear}
        picture(frame, ts, level)
        looks.append(frame)
        return "First character frame saved."

    if gear_changed:
        frame = {"t": ts, "level": level, "itemLevel": api.get("itemLevel"), "gear": gear}
        if new_render:
            picture(frame, ts, level)
            looks.append(frame)
            return "New gear and a new render: frame saved."
        # The Armory hasn't redrawn him yet. Show its last picture until it does.
        frame.update(img=last["img"], w=last.get("w"), h=last.get("h"), hash=last.get("hash"), stalePic=True)
        looks.append(frame)
        return "New gear: frame saved with the Armory's last render until it redraws him."

    if new_render:
        if last.get("stalePic"):
            # The Armory caught up with gear an earlier check already saved: swap the new picture in.
            picture(last, last["t"], last["level"])
            return "The Armory redrew him: new render added to the latest frame."
        frame = {"t": ts, "level": level, "itemLevel": api.get("itemLevel"), "gear": gear if gear_known else last_gear}
        picture(frame, ts, level)
        looks.append(frame)
        return "New look: frame saved."

    if not gear_known:
        return "Armory sent no gear list. Look unchanged."
    return "Gear and look unchanged."


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--min-gap", type=float, default=0, metavar="MINUTES",
                    help="do nothing if the last check was less than this many minutes ago")
    args = ap.parse_args(argv)

    data = json.loads(DATA.read_text(encoding="utf-8"))
    if args.min_gap and checked_recently(data, args.min_gap):
        print(f"Checked the Armory at {data['checkedAt']}, under {args.min_gap:g} minutes ago. Skipping this run.")
        return 0
    try:
        api = json.loads(get(API, "application/json"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"Could not reach the Armory: {exc}")
        return 1

    level, ts = api.get("level"), api.get("lastLoginTs")
    if not isinstance(level, int) or not isinstance(ts, int):
        print("The Armory response had no level or login time. Nothing changed.")
        return 1

    prev_char = data.get("character") or {}
    professions = [
        {"name": p.get("name"), "skill": p.get("skill"), "max": p.get("max"), "primary": p.get("primary")}
        for p in api.get("professions") or []
    ]
    kept = []
    if not professions and prev_char.get("professions"):
        professions = prev_char["professions"]  # the Armory sometimes leaves them out; keep the last known
        kept.append("professions")
    data["character"] = {
        "name": api.get("name"),
        "region": api.get("region"),
        "ruleset": api.get("realm"),
        "race": api.get("race"),
        "className": api.get("className"),
        "spec": api.get("spec"),
        "faction": api.get("faction"),
        "itemLevel": api.get("itemLevel"),
        "lastLoginTs": ts,
        "professions": professions,
    }
    data["armoryUrl"] = ARMORY_PAGE

    snaps = data.setdefault("snapshots", [])
    new_snap = not any(s["t"] == ts for s in snaps)
    if new_snap:
        snaps.append({"t": ts, "level": level})
        snaps.sort(key=lambda s: s["t"])

    look_note = update_looks(data.setdefault("looks", []), api, ts, level)

    data["checkedAt"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    new_stats = update_stats(api, ts, level, data["checkedAt"], kept)

    seen = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
    print(f"Level {level}, last seen {seen:%Y-%m-%d %H:%M} UTC."
          f" {'New level snapshot.' if new_snap else 'No new logout.'}"
          f" {look_note} {new_stats}"
          + (f" The Armory left out {', '.join(kept)}; kept the last known values." if kept else ""))
    return 0


# Reputation standings as cumulative points from the start of Neutral, so a trend line can cross standings.
REP_OFFSET = {0: -42000, 1: -6000, 2: -3000, 3: 0, 4: 3000, 5: 9000, 6: 21000, 7: 42000}


def flat_stats(record):
    out = {}

    def walk(cat):
        for s in cat.get("stats") or []:
            if isinstance(s.get("value"), (int, float)):
                out[str(s["id"])] = s["value"]
        for sub in cat.get("sub") or []:
            walk(sub)

    for c in record.get("categories") or []:
        walk(c)
    return out


def merge_record(new, old):
    """Put back stats, and whole categories, that an Armory record response left out, at their last values.
    The Armory sometimes answers with part of the record; counters only go up, so the old value is the best guess."""
    restored = 0

    def merge(new_cats, old_cats):
        nonlocal restored
        by_id = {c.get("id"): c for c in new_cats}
        for i, oc in enumerate(old_cats):
            nc = by_id.get(oc.get("id"))
            if nc is None:
                new_cats.insert(min(i, len(new_cats)), oc)
                restored += len(flat_stats({"categories": [oc]}))
                continue
            have = {st.get("id") for st in nc.get("stats") or []}
            stats = nc.setdefault("stats", [])
            for j, st in enumerate(oc.get("stats") or []):
                if st.get("id") not in have:
                    stats.insert(min(j, len(stats)), st)
                    restored += 1
            if oc.get("sub"):
                merge(nc.setdefault("sub", []), oc["sub"])

    merge(new.setdefault("categories", []), (old or {}).get("categories") or [])
    return restored


def update_stats(api, ts, level, checked_at, kept):
    """Save the Armory record (kills, quests, deaths, ...) plus professions and reputation to data/stats.json.
    Anything the Armory leaves out of a response keeps its last known value; what was kept is added to `kept`."""
    path = ROOT / "data" / "stats.json"
    stats = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"snaps": []}
    try:
        record = json.loads(get(API.replace("?ns=", "/record?ns="), "application/json"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"Record not available ({exc})."
    if not record.get("categories"):
        return "Record came back empty."

    if merge_record(record, stats.get("record")):
        kept.append("some record stats")
    stats["record"] = record
    for key in ("professions", "reputations"):
        if api.get(key):
            stats[key] = api[key]
        elif stats.get(key):
            if key not in kept:
                kept.append(key)
        else:
            stats[key] = []
    stats["honorableKills"] = api.get("honorableKills", stats.get("honorableKills"))
    stats["checkedAt"] = checked_at
    snaps = stats.setdefault("snaps", [])
    added = False
    if not any(s["t"] == ts for s in snaps):
        snaps.append({
            "t": ts,
            "level": level,
            "ilvl": api.get("itemLevel"),
            "s": flat_stats(record),
            "prof": {p["name"]: p.get("skill") for p in stats["professions"] if p.get("name")},
            "rep": {r["name"]: REP_OFFSET.get(r.get("tier"), 0) + (r.get("value") or 0)
                    for r in stats["reputations"] if r.get("name")},
        })
        snaps.sort(key=lambda s: s["t"])
        added = True
    path.write_text(json.dumps(stats, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return "New stats snapshot." if added else "Stats unchanged."


if __name__ == "__main__":
    sys.exit(main())
