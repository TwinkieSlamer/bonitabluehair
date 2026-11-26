#!/usr/bin/env python3
"""Check Bonita Bluehair in WoW: Forever and update the site's data.

Reads Blizzard's official World of Warcraft API (his "Armory" data). Run by GitHub Actions every hour (see
.github/workflows/update.yml), which passes the API client's ID and secret from the repository's Actions secrets:

    pip install pillow
    BLIZZARD_CLIENT_ID=... BLIZZARD_CLIENT_SECRET=... python scripts/update.py

What it does:
  * records a level snapshot each time his character sheet shows a new logout
  * also reads his level from his guild's roster, which follows the game
    while he is still online, and records a snapshot when the roster is
    ahead of his sheet
  * saves a new gear-reel frame whenever his equipped gear changes, or the
    character render changes (a new look). Blizzard redraws the render
    later than it updates the gear, so a gear change is saved right away with
    its last picture, and the picture is swapped in when the render catches up.
    Its picture server sometimes hands back an older picture; that is ignored
  * saves his professions, reputations and record (kills, quests, deaths...)
  * keeps the last known professions, reputations and record stats when a
    reply comes back without them
  * writes everything to data/history.json and data/stats.json, which the pages read

    python scripts/update.py --min-gap 40   # skip if the last check was under 40 minutes ago
"""
import argparse
import base64
import datetime as dt
import email.utils
import hashlib
import http.client
import io
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageChops

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "history.json"
RENDERS = ROOT / "renders"
ITEM_LEVELS = ROOT / "data" / "item-levels.json"   # item id -> item level, kept so each item is looked up once
# The source is Blizzard's official World of Warcraft API (https://develop.battle.net). WoW: Forever is the "forever"
# game version there. Its characters have a first and last name and no realm, so he is simply
# /profile/wow/character/bonita-bluehair in the namespace profile-forever-us. scripts/blizzard_probe.py is how that
# was found, and prints the shape of every reply used here.
# Until Nov 14, 2026 this script read the same data through classicarmory.gg's internal feed. That site then closed
# the feed to outside programs (403 Forbidden on every /api/ address), which is its owner's call, so the tracker
# moved to the official API rather than work around it.
BLIZZARD = "https://us.api.blizzard.com"
TOKEN_URL = "https://oauth.battle.net/token"
NAMESPACE = "profile-forever-us"
SLUG = "bonita-bluehair"
CHARACTER = f"/profile/wow/character/{SLUG}"
EXTRA_KEYS = ("professions", "reputations")
ARMORY_PAGE = "https://classicarmory.gg/character/us/forever/bonita-bluehair"  # a page for people; the site links to it
UA = {"User-Agent": "christmas-bet-tracker/1.0 (+https://bonitabluehair.com)"}

# Set this to a sentence to make every check fetch nothing, change nothing and print the sentence (used Nov 14-15,
# 2026, between the Armory feed closing and the move to Blizzard's API). The pages show a "paused" note while
# data/history.json has a "paused" entry; a successful check removes it.
PAUSED = None

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


def get(url, accept="*/*", headers=None, meta=None):
    """Fetch a URL, waiting and trying again through rate limits, server errors and dropped connections.
    A dict passed as `meta` gets the reply's Last-Modified header (the date the server gives the file)."""
    req = urllib.request.Request(url, headers={**UA, "Accept": accept, **(headers or {})})
    retries = len(RETRY_DELAYS)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if meta is not None:
                    meta["Last-Modified"] = resp.headers.get("Last-Modified")
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


UNDRAWN = {"Neck", "Finger", "Trinket", "Relic"}  # slots that don't appear on a character, so not in his picture


def drawn_key(gear):
    """gear_key for the items a picture of him shows."""
    return gear_key([g for g in gear or [] if g.get("slot") not in UNDRAWN])


def cropped(png_bytes):
    """The Armory render trimmed to the figure, with a little room around it."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    box = im.getchannel("A").getbbox()
    if box:
        pad = 24
        im = im.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                      min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
    return im


def same_picture(png_bytes):
    """True when a render with a new hash is the picture already saved, drawn again.
    Blizzard sometimes re-renders him with a few dozen pixels different (79 of 272,000 on Nov 10, 2026): a new file,
    the same look. Compares against renders/latest.png, the last picture saved, and allows 0.2% of pixels to differ."""
    latest = RENDERS / "latest.png"
    if not latest.exists():
        return False
    try:
        new, old = cropped(png_bytes), Image.open(latest).convert("RGBA")
    except OSError:
        return False
    if new.size != old.size:
        return False
    flat = [Image.alpha_composite(Image.new("RGBA", im.size, (10, 15, 30, 255)), im).convert("RGB") for im in (new, old)]
    differing = sum(ImageChops.difference(*flat).convert("L").histogram()[25:])  # off by more than 24 of 255
    return differing <= new.width * new.height * 0.002


def file_date(text):
    """A reply's Last-Modified header as milliseconds, or None when it is missing or unreadable."""
    try:
        return int(email.utils.parsedate_to_datetime(text).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def older_picture(looks, digest, drawn_at):
    """True when a picture that differs from the reel's newest one is an older picture, served again.
    Blizzard's picture server answers from more than one copy of his file, and a copy can be days behind: on
    Nov 18, 2026 about half the hourly checks got his Nov 16 picture back in place of the one drawn that morning, and
    the reel filed it as a new look three times. The file's own date settles it when both dates are known. Without
    them, a picture is an old one when an earlier frame already has it."""
    held = looks[-1].get("picAt")
    if drawn_at and held and drawn_at != held:
        return drawn_at < held
    return any(look.get("hash") == digest for look in looks[:-1])


def save_render(png_bytes, stamp, level):
    im = cropped(png_bytes)
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

    png = digest = drawn_at = None
    if api.get("mainRender"):
        try:
            meta = {}
            png = get(api["mainRender"], "image/png", meta=meta)
            digest = hashlib.sha256(png).hexdigest()
            drawn_at = file_date(meta.get("Last-Modified"))  # when Blizzard made this picture file
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"Could not fetch the character render ({exc}). Level data still saved.")
    went_back = ""
    if last is not None and digest is not None and digest != last.get("hash") and older_picture(looks, digest, drawn_at):
        # Not a redraw: carry on as if no picture had come, so the reel keeps the newer one it has.
        dated_text = (dt.datetime.fromtimestamp(drawn_at / 1000, dt.timezone.utc).strftime("file dated %b %d %H:%M UTC")
                      if drawn_at else "no file date")
        went_back = f" Blizzard's picture server sent an older picture of him again ({dated_text}): ignored."
        png = digest = drawn_at = None
    new_render = digest is not None and (last is None or digest != last.get("hash"))

    def dated(frame):
        if drawn_at:
            frame["picAt"] = drawn_at
        else:
            frame.pop("picAt", None)

    def picture(frame, t, lvl):
        path, size = save_render(png, frame_stamp(t), lvl)
        frame.update(img=path, w=size[0], h=size[1], hash=digest)
        dated(frame)
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
        # The Armory hasn't redrawn him yet, so the frame borrows its last picture. That picture is only behind when
        # something it shows changed, or it was already behind: a new necklace or ring looks the same.
        frame.update(img=last["img"], w=last.get("w"), h=last.get("h"), hash=last.get("hash"))
        if last.get("picAt"):
            frame["picAt"] = last["picAt"]
        if last.get("stalePic") or drawn_key(gear) != drawn_key(last_gear):
            frame["stalePic"] = True
            looks.append(frame)
            return "New gear: frame saved with the Armory's last render until it redraws him." + went_back
        looks.append(frame)
        return "New gear that his picture doesn't show: frame saved with the current render." + went_back

    if new_render:
        if last.get("stalePic"):
            # The Armory caught up with gear an earlier check already saved: swap the new picture in.
            picture(last, last["t"], last["level"])
            return "The Armory redrew him: new render added to the latest frame."
        if same_picture(png):
            last["hash"] = digest  # a new file, the same look: nothing to add to the reel
            dated(last)
            return "The Armory redrew the same picture. Look unchanged."
        if last["t"] == ts:
            # A second, different picture for the same logout. Two frames would share one file name, and the reel
            # would show the same moment twice, so the picture replaces the one on this frame.
            picture(last, ts, last["level"])
            return "The Armory redrew him again for the same logout: picture replaced on the latest frame."
        frame = {"t": ts, "level": level, "itemLevel": api.get("itemLevel"), "gear": gear if gear_known else last_gear}
        picture(frame, ts, level)
        looks.append(frame)
        return "New look: frame saved."

    if not gear_known:
        return "Armory sent no gear list. Look unchanged." + went_back
    return "Gear and look unchanged." + went_back


class SourceError(Exception):
    """The API client can't be used: its ID and secret are missing or refused."""


_token = None


def blizzard_token():
    """An access token for the API client whose ID and secret are in the environment. None of the three is ever printed."""
    global _token
    if _token:
        return _token
    cid = os.environ.get("BLIZZARD_CLIENT_ID", "").strip()
    secret = os.environ.get("BLIZZARD_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        raise SourceError("BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET are not set (repository Actions secrets; see the README)")
    req = urllib.request.Request(TOKEN_URL, data=b"grant_type=client_credentials", headers={
        **UA, "Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode(),
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SourceError(f"Blizzard refused the API client's ID and secret (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SourceError(f"could not get an access token ({exc})") from None
    _token = body.get("access_token") if isinstance(body, dict) else None
    if not _token:
        raise SourceError("Blizzard's token reply had no token in it")
    return _token


def bz(path):
    """One reply from Blizzard's API, parsed. The token travels in a header, so it is never part of a logged URL."""
    url = f"{BLIZZARD}{path}?namespace={NAMESPACE}&locale=en_US"
    return json.loads(get(url, "application/json", {"Authorization": "Bearer " + blizzard_token()}))


def optional(what, path):
    """A reply the check can live without: None, with a line in the log, when it can't be had."""
    try:
        reply = bz(path)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"Could not get {what} ({exc}).")
        return None
    return reply if isinstance(reply, dict) else None


def named(x):
    return x.get("name") if isinstance(x, dict) else None


# Blizzard's slot types -> the slot keys in SLOT_ORDER.
SLOT_KEYS = {"HEAD": "head", "NECK": "neck", "SHOULDER": "shoulder", "BACK": "back", "CHEST": "chest", "SHIRT": "shirt",
             "TABARD": "tabard", "WRIST": "wrist", "HANDS": "hands", "WAIST": "waist", "LEGS": "legs", "FEET": "feet",
             "FINGER_1": "finger1", "FINGER_2": "finger2", "TRINKET_1": "trinket1", "TRINKET_2": "trinket2",
             "MAIN_HAND": "mainhand", "OFF_HAND": "offhand", "RANGED": "ranged"}


def to_equipment(reply):
    """Blizzard's equipped_items as {slot key: item}, with the labels the gear reel has always used
    (inventory type "Finger", "Two-Hand", "Relic"..., quality in lower case)."""
    out = {}
    for it in (reply or {}).get("equipped_items") or []:
        key = SLOT_KEYS.get((it.get("slot") or {}).get("type"))
        if not key or not it.get("name"):
            continue
        out[key] = {"id": (it.get("item") or {}).get("id"), "name": it["name"],
                    "quality": str((it.get("quality") or {}).get("type") or "").lower() or None,
                    "itemLevel": (it.get("level") or {}).get("value"),
                    "slotLabel": named(it.get("inventory_type")) or named(it.get("slot"))}
    return out


# Since Nov 25, 2026 Blizzard's API leaves out item levels: his average in the summary and each item's in the
# equipment reply. Its item catalogue only knows the older items (the WoW: Forever ones answer 404), so each item's
# level comes from Wowhead's tooltip feed (data set 16 is WoW: Forever), which agreed with Blizzard on all 18 items
# both had numbers for. A level is looked up once and kept in data/item-levels.json; levels Blizzard does send are
# kept there too.
WOWHEAD_TOOLTIP = "https://nether.wowhead.com/tooltip/item/{}?dataEnv=16&locale=0"


def wowhead_level(item_id):
    """An item's level from Wowhead's tooltip, or None."""
    try:
        reply = json.loads(get(WOWHEAD_TOOLTIP.format(int(item_id)), "application/json"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"Could not look up item {item_id} on Wowhead ({exc}).")
        return None
    m = re.search(r"Item Level (?:<!--ilvl-->)?(\d+)", str((reply or {}).get("tooltip") or ""))
    return int(m.group(1)) if m else None


def fill_item_levels(equipment):
    """Give every equipped item its level: Blizzard's when it sends one, else the saved table, else Wowhead."""
    try:
        table = json.loads(ITEM_LEVELS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        table = {}
    changed, looked_up = False, []
    for it in (equipment or {}).values():
        key = str(it.get("id"))
        if it.get("id") is None:
            continue
        if it.get("itemLevel") is not None:
            if table.get(key) != it["itemLevel"]:
                table[key] = it["itemLevel"]; changed = True
            continue
        if key not in table:
            level = wowhead_level(it["id"])
            if level is None:
                continue
            table[key] = level; changed = True
            looked_up.append(f"{it.get('name')} {level}")
            time.sleep(0.3)
        it["itemLevel"] = table[key]
    if changed:
        ITEM_LEVELS.write_text(json.dumps(dict(sorted(table.items(), key=lambda kv: int(kv[0]))), indent=1) + "\n", encoding="utf-8")
    if looked_up:
        print("Item levels looked up on Wowhead: " + ", ".join(looked_up) + ".")


AVERAGE_SLOTS = ("head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet",
                 "finger1", "finger2", "trinket1", "trinket2", "mainhand", "offhand")


def equipped_level(equipment):
    """His item level the way Blizzard worked it out: the 16 slots above (no shirt, tabard or relic), a two-handed
    weapon counted again for the empty off hand, an empty slot as 0, divided by 16 and rounded down. It matched
    Blizzard's number on all 14 gear frames saved before Nov 25, 2026. None when an equipped item's level is unknown."""
    eq = equipment or {}
    total = 0
    for slot in AVERAGE_SLOTS:
        it = eq.get(slot)
        if slot == "offhand" and not it and (eq.get("mainhand") or {}).get("slotLabel") == "Two-Hand":
            it = eq["mainhand"]
        if not it:
            continue
        if it.get("itemLevel") is None:
            return None
        total += it["itemLevel"]
    return total // 16 if eq else None


def to_professions(reply):
    rows = []
    for kind, primary in (("primaries", True), ("secondaries", False)):
        for p in (reply or {}).get(kind) or []:
            tiers = p.get("tiers") or []
            tier = max(tiers, key=lambda t: t.get("max_skill_points") or 0) if tiers else {}
            rows.append({"id": (p.get("profession") or {}).get("id"), "name": named(p.get("profession")), "primary": primary,
                         "skill": tier.get("skill_points"), "max": tier.get("max_skill_points"),
                         "recipes": sum(len(t.get("known_recipes") or []) for t in tiers)})
    return [r for r in rows if r["name"]]


def to_reputations(reply):
    rows = []
    for r in (reply or {}).get("reputations") or []:
        st = r.get("standing") or {}
        rows.append({"id": (r.get("faction") or {}).get("id"), "name": named(r.get("faction")), "standing": st.get("name"),
                     "tier": st.get("tier"), "value": st.get("value"), "max": st.get("max")})
    return [r for r in rows if r["name"]]


def to_record(reply):
    """Blizzard's achievement statistics as the record the site saves: categories of {id, name, value[, detail]}.
    Counts arrive as floats; whole ones become ints and the rest keep one decimal, as the saved record always had."""
    def number(q):
        if isinstance(q, bool) or not isinstance(q, (int, float)):
            return q
        return int(q) if float(q).is_integer() else math.floor(q * 10 + 0.5) / 10

    def stat(s):
        row = {"id": s.get("id"), "name": s.get("name"), "value": number(s.get("quantity"))}
        if s.get("description"):
            row["detail"] = s["description"]
        return row

    def cat(c, top):
        row = {"id": c.get("id"), "name": c.get("name"), "stats": [stat(s) for s in c.get("statistics") or []]}
        subs = [cat(x, False) for x in c.get("sub_categories") or []]
        if top or subs:  # a top-level category always lists its sub-categories, even when it has none
            row["sub"] = subs
        return row

    cats = (reply or {}).get("categories")
    return {"categories": [cat(c, True) for c in cats]} if cats else None


def read_character():
    """Everything the tracker uses, read from Blizzard's API and laid out the way the rest of this script has always
    worked with it, so the saved data keeps its shape. Only the summary (level and last logout) is essential; a
    part that can't be had is left out and the last known values stay."""
    summary = bz(CHARACTER)
    if not isinstance(summary, dict):
        raise ValueError("the character summary was not an object")
    api = {
        "name": summary.get("name_search") or " ".join(x for x in (summary.get("name"), summary.get("surname")) if x),
        "slug": SLUG, "region": "us", "realm": named(summary.get("ruleset")),
        "level": summary.get("level"), "lastLoginTs": summary.get("last_login_timestamp"), "xp": summary.get("experience"),
        "race": named(summary.get("race")), "className": named(summary.get("character_class")),
        "faction": named(summary.get("faction")), "itemLevel": summary.get("equipped_item_level"),
        "guildSlug": (summary.get("guild") or {}).get("slug"),
    }
    api["equipment"] = to_equipment(optional("his gear", CHARACTER + "/equipment"))
    fill_item_levels(api["equipment"])
    if api["itemLevel"] is None:
        api["itemLevel"] = equipped_level(api["equipment"])
    media = optional("his picture's address", CHARACTER + "/character-media")
    api["mainRender"] = next((a.get("value") for a in (media or {}).get("assets") or [] if a.get("key") == "main-raw"), None)
    specs = optional("his talents", CHARACTER + "/specializations")
    active = next((g for g in (specs or {}).get("specialization_groups") or [] if g.get("is_active")), None)
    trees = (active or {}).get("specializations") or []
    if trees:
        api["spec"] = max(trees, key=lambda t: t.get("spent_points") or 0).get("specialization_name")
    pvp = optional("his PvP summary", CHARACTER + "/pvp-summary")
    if isinstance((pvp or {}).get("honorable_kills"), int):
        api["honorableKills"] = pvp["honorable_kills"]
    api["professions"] = to_professions(optional("his professions", CHARACTER + "/professions"))
    api["reputations"] = to_reputations(optional("his reputations", CHARACTER + "/reputations"))
    api["record"] = to_record(optional("his record", CHARACTER + "/achievements/statistics"))
    return api


def roster_level(api):
    """His level on his guild's roster, or None when it can't be read.
    The character sheet (level, gear, stats) only refreshes when he logs out. The guild roster follows the game more
    closely, so it shows a new level while he is still online: on Nov 11, 2026 it said 34 for hours while the sheet
    said 33. The guild comes from the sheet, so this keeps working if he changes guilds, and stops if he leaves."""
    guild = api.get("guildSlug")
    if not guild:
        return None
    roster = optional("the guild roster", f"/data/wow/guild/{urllib.parse.quote(str(guild), safe='')}/roster")
    members = (roster or {}).get("members")
    for m in members if isinstance(members, list) else []:
        c = m.get("character") if isinstance(m, dict) else None
        if not isinstance(c, dict) or c.get("slug") != SLUG:
            continue
        lvl = c.get("level")
        return lvl if isinstance(lvl, int) and not isinstance(lvl, bool) and 1 <= lvl <= 60 else None
    return None


def like(old, new):
    """`new` rows in the order `old` had them (matched by id), anything new after. Blizzard lists things in its own
    order; keeping the saved order means a check that changes nothing changes nothing in the files."""
    place = {row.get("id"): i for i, row in enumerate(old or []) if isinstance(row, dict)}
    return sorted(new, key=lambda row: place.get(row.get("id"), len(place)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--min-gap", type=float, default=0, metavar="MINUTES",
                    help="do nothing if the last check was less than this many minutes ago")
    args = ap.parse_args(argv)
    if PAUSED:
        print(PAUSED)
        return 0

    data = json.loads(DATA.read_text(encoding="utf-8"))
    if args.min_gap and checked_recently(data, args.min_gap):
        print(f"Last checked at {data['checkedAt']}, under {args.min_gap:g} minutes ago. Skipping this run.")
        return 0
    try:
        api = read_character()
    except SourceError as exc:
        print(f"Could not use Blizzard's API: {exc}. Nothing changed.")
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"Could not reach Blizzard's API: {exc}. Nothing changed.")
        return 1

    level, ts = api.get("level"), api.get("lastLoginTs")
    if not isinstance(level, int) or isinstance(level, bool) or not isinstance(ts, int):
        print("Blizzard's reply had no level or login time. Nothing changed.")
        return 1

    data.pop("paused", None)  # a check got through: the pages stop saying updates are paused
    prev_char = data.get("character") or {}
    professions = [
        {"name": p.get("name"), "skill": p.get("skill"), "max": p.get("max"), "primary": p.get("primary")}
        for p in api.get("professions") or []
    ]
    # Keep the order they were saved in, so the race page's "Herbalism · Alchemy" doesn't flip with the API's order.
    place = {p.get("name"): i for i, p in enumerate(prev_char.get("professions") or [])}
    professions.sort(key=lambda p: place.get(p["name"], len(place)))
    kept = []
    if not professions and prev_char.get("professions"):
        professions = prev_char["professions"]  # a reply without them: keep the last known
        kept.append("professions")
    data["character"] = {
        "name": api.get("name"),
        "region": api.get("region"),
        "ruleset": api.get("realm"),
        "race": api.get("race"),
        "className": api.get("className"),
        "spec": api.get("spec") or prev_char.get("spec"),
        "faction": api.get("faction"),
        "itemLevel": api.get("itemLevel"),
        "lastLoginTs": ts,
        "xp": api.get("xp"),  # XP into his current level, as Blizzard reports it (nothing on the pages uses it yet)
        "professions": professions,
    }
    data["armoryUrl"] = ARMORY_PAGE

    snaps = data.setdefault("snapshots", [])
    new_snap = not any(s["t"] == ts for s in snaps)
    if new_snap:
        snaps.append({"t": ts, "level": level})
        snaps.sort(key=lambda s: s["t"])

    # A level the roster shows before his sheet does. It is stamped with the time of this check: he reached it some
    # time since the last one. His next logout adds its own snapshot as usual.
    roster, roster_note = roster_level(api), ""
    if roster is not None and roster > max(s["level"] for s in snaps):
        snaps.append({"t": int(time.time() * 1000), "level": roster, "source": "roster"})
        snaps.sort(key=lambda s: s["t"])
        roster_note = f" The guild roster has him at level {roster}, ahead of his character sheet: level snapshot added."

    look_note = update_looks(data.setdefault("looks", []), api, ts, level)

    data["checkedAt"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    new_stats = update_stats(api, ts, level, data["checkedAt"], kept)

    seen = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc)
    print(f"Level {level}, last seen {seen:%Y-%m-%d %H:%M} UTC."
          f" {'New level snapshot.' if new_snap else 'No new logout.'}{roster_note}"
          f" {look_note} {new_stats}"
          + (f" Blizzard's API left out {', '.join(kept)}; kept the last known values." if kept else ""))
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


def order_record(new, old):
    """Put the new record's categories, sub-categories and stats in the order the saved record has them."""
    def order(new_cats, old_cats):
        new_cats[:] = like(old_cats, new_cats)
        by_id = {c.get("id"): c for c in old_cats or []}
        for nc in new_cats:
            oc = by_id.get(nc.get("id")) or {}
            nc["stats"] = like(oc.get("stats"), nc.get("stats") or [])
            if nc.get("sub"):
                order(nc["sub"], oc.get("sub"))

    order(new.setdefault("categories", []), (old or {}).get("categories"))


def merge_record(new, old):
    """Put back stats, and whole categories, that a record reply left out, at their last values.
    Counters only go up, so the old value is the best guess."""
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
    """Save his record (kills, quests, deaths, ...) plus professions and reputation to data/stats.json.
    Anything a reply leaves out keeps its last known value; what was kept is added to `kept`."""
    path = ROOT / "data" / "stats.json"
    stats = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"snaps": []}
    record = api.get("record")
    if not record or not record.get("categories"):
        return "Record not available."

    order_record(record, stats.get("record"))
    if merge_record(record, stats.get("record")):
        kept.append("some record stats")
    stats["record"] = record
    for key in EXTRA_KEYS:
        if api.get(key):
            stats[key] = like(stats.get(key), api[key])
        elif stats.get(key):
            if key not in kept:
                kept.append(key)
        else:
            stats[key] = []
    stats["honorableKills"] = api.get("honorableKills", stats.get("honorableKills"))
    stats["checkedAt"] = checked_at
    snaps = stats.setdefault("snaps", [])
    now = {
        "prof": {p["name"]: p.get("skill") for p in stats["professions"] if p.get("name")},
        "rep": {r["name"]: REP_OFFSET.get(r.get("tier"), 0) + (r.get("value") or 0)
                for r in stats["reputations"] if r.get("name")},
    }
    snap = next((s for s in snaps if s["t"] == ts), None)
    if snap is None:
        snaps.append({"t": ts, "level": level, "ilvl": api.get("itemLevel"), "s": flat_stats(record), **now})
        snaps.sort(key=lambda s: s["t"])
        note = "New stats snapshot."
    else:
        # Skills and standings are as of his last logout, like the level. A snapshot saved while the Armory was
        # leaving them out carried the values from before; now that they've arrived, put the real ones in.
        fixed = [key for key, field in zip(EXTRA_KEYS, ("prof", "rep")) if api.get(key) and snap.get(field) != now[field]]
        for key, field in zip(EXTRA_KEYS, ("prof", "rep")):
            if key in fixed:
                snap[field] = now[field]
        note = f"Stats snapshot corrected ({', '.join(fixed)})." if fixed else "Stats unchanged."
    path.write_text(json.dumps(stats, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return note


if __name__ == "__main__":
    sys.exit(main())
