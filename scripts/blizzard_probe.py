#!/usr/bin/env python3
"""Find out what Blizzard's official API offers for Bonita Bluehair in WoW: Forever.

Run by the "Blizzard API probe" workflow (Actions tab -> Blizzard API probe -> Run workflow), which passes the API
client's ID and secret from the repository's Actions secrets. It gets a token, checks whether the API knows a
"forever" game version at all, tries the ways a Forever character could be addressed, and for an address that
answers with HIM (name, race and class checked) prints the status and shape of every endpoint the tracker needs.

It prints public game data only: never the token, the client ID or the secret. It makes about 60 requests.

What the first run (Nov 15, 2026) showed: the client works; "dynamic-forever-us" has no realm list; nothing answers
at /profile/wow/character/normal/<name> in "profile-forever-us"; and a bare "bonita" on other game versions is
someone else's character, which is why a match now has to be him.
"""
import base64
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REGION = "us"
HOST = f"https://{REGION}.api.blizzard.com"
UA = "christmas-bet-tracker/1.0 (+https://bonitabluehair.com)"
FIRST, LAST = "bonita", "bluehair"
CHAR_ID = 1255157  # from his picture's address: render.worldofwarcraft.com/forever-us/character/245/1255157-main-raw.png
GUILD = "borazzo-bay-pirates"
FOREVER, KNOWN, BOGUS = "forever", "classicann", "doesnotexist"
SUB = ["status", "equipment", "character-media", "statistics", "achievements/statistics", "professions",
       "reputations", "specializations", "pvp-summary"]
results = []
DUMP = None  # with --dump DIR, the full replies about him are also written there as JSON (the workflow uploads them)


def save(name, data):
    if DUMP is not None and data is not None:
        DUMP.mkdir(parents=True, exist_ok=True)
        (DUMP / f"{name.replace('/', '-')}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def ns(kind, flavor):
    return "-".join(x for x in (kind, flavor, REGION) if x)


def token():
    cid = os.environ.get("BLIZZARD_CLIENT_ID", "").strip()
    secret = os.environ.get("BLIZZARD_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        sys.exit("BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET are not set. Save both as repository Actions secrets (see the README).")
    req = urllib.request.Request(
        "https://oauth.battle.net/token", data=b"grant_type=client_credentials",
        headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode(),
                 "Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            detail = f"{err.get('error')}: {err.get('error_description')}"
        except ValueError:
            detail = "no readable reason"
        sys.exit(f"Blizzard refused the client ID and secret: HTTP {e.code} ({detail}). Check the two secrets were pasted whole.")
    print(f"Token granted: type {body.get('token_type')}, lasts {body.get('expires_in')} seconds.")
    return body["access_token"]


def get(tok, path, namespace, label=None):
    """GET one API path. Returns (status, parsed JSON or None). Waits once through a rate limit."""
    sep = "&" if "?" in path else "?"
    url = (path if path.startswith("http") else HOST + path) + f"{sep}namespace={namespace}&locale=en_US"
    for attempt in (1, 2):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok, "User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
            if status == 429 and attempt == 1:
                wait = min(float(e.headers.get("Retry-After") or 5), 30)
                print(f"    rate limited, waiting {wait:.0f}s")
                time.sleep(wait)
                continue
        except (urllib.error.URLError, TimeoutError) as e:
            status, raw = 0, str(e).encode()
        break
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if label:
        results.append((label, namespace, status))
    time.sleep(0.15)
    return status, data


def reason(data):
    if isinstance(data, dict) and (data.get("detail") or data.get("code") or data.get("type")):
        return f" ({data.get('code')} {data.get('type')}: {data.get('detail')})"
    return ""


def is_him(data):
    """A character summary only counts when it is him: the full name, or a Night Elf Druid called Bonita."""
    if not isinstance(data, dict):
        return False
    name = str(data.get("name") or "").lower().replace("-", " ")
    race, cls = (data.get("race") or {}).get("name"), (data.get("character_class") or {}).get("name")
    return name == f"{FIRST} {LAST}" or (name.startswith(FIRST) and race == "Night Elf" and cls == "Druid")


def who(data):
    if not isinstance(data, dict):
        return ""
    return (f" -> {data.get('name')!r}, level {data.get('level')}, {(data.get('race') or {}).get('name')}"
            f" {(data.get('character_class') or {}).get('name')}, realm {(data.get('realm') or {}).get('slug')}")


def shape(v, indent=1, depth=0, budget=None):
    """Print the structure of a response: keys, types, short samples. Lists show their length and first element."""
    budget = budget if budget is not None else [90]
    pad = "    " * indent
    if isinstance(v, dict):
        for k, x in v.items():
            if k == "_links" or budget[0] <= 0:
                continue
            budget[0] -= 1
            if isinstance(x, dict):
                if set(x) == {"href"}:
                    print(f"{pad}{k}: link {x['href'].split('.com', 1)[-1][:110]}")
                elif depth >= 4:
                    print(f"{pad}{k}: {{...{len(x)} keys}}")
                else:
                    print(f"{pad}{k}:")
                    shape(x, indent + 1, depth + 1, budget)
            elif isinstance(x, list):
                print(f"{pad}{k}: list of {len(x)}" + ("" if x else " (empty)"))
                if x and depth < 4:
                    shape(x[0], indent + 1, depth + 1, budget) if isinstance(x[0], (dict, list)) else print(f"{pad}    first: {x[0]!r:.80}")
            else:
                print(f"{pad}{k}: {type(x).__name__} {x!r:.90}")
    elif isinstance(v, list):
        print(f"{pad}list of {len(v)}")
        if v:
            shape(v[0], indent + 1, depth + 1, budget)
    else:
        print(f"{pad}{type(v).__name__} {v!r:.90}")
    if budget[0] <= 0 and depth == 0:
        print(f"{pad}... (cut short)")


def main():
    global DUMP
    if "--dump" in sys.argv:
        DUMP = pathlib.Path(sys.argv[sys.argv.index("--dump") + 1])
    tok = token()

    print(f"\n== 1. Does the API know a '{FOREVER}' game version? (compared with '{KNOWN}', which exists, and '{BOGUS}', which doesn't)")
    checks = [("static", "/data/wow/playable-class/index"), ("static", "/data/wow/playable-race/index"),
              ("static", "/data/wow/item/9624"), ("static", "/data/wow/item/273047"),
              ("dynamic", "/data/wow/realm/index"), ("dynamic", "/data/wow/connected-realm/index")]
    same_as_bogus = 0
    for kind, path in checks:
        row = []
        for flavor in (FOREVER, KNOWN, BOGUS):
            status, data = get(tok, path, ns(kind, flavor))
            extra = ""
            if status == 200 and isinstance(data, dict):
                extra = " " + (repr(data.get("name"))[:40] if data.get("name") else ", ".join(f"{k}[{len(v)}]" for k, v in data.items() if isinstance(v, list))[:60])
            row.append((status, f"{ns(kind, flavor)}: HTTP {status}{reason(data) if status != 200 else extra}"))
        same_as_bogus += row[0][0] == row[2][0] and row[0][0] != 200
        print(f"  {path}\n      " + "\n      ".join(text for _, text in row))
    print(f"  -> '{FOREVER}' answered like the made-up version on {same_as_bogus} of {len(checks)} checks.")

    print("\n== 2. Realm names that could be Forever's, in the versions that do have realm lists")
    for flavor in ("classic1x", KNOWN, "classic", ""):
        status, data = get(tok, "/data/wow/realm/index", ns("dynamic", flavor))
        realms = [(r.get("slug"), r.get("name")) for r in (data or {}).get("realms", [])] if isinstance(data, dict) else []
        odd = [f"{s} ({n})" for s, n in realms if any(w in f"{s} {n}".lower() for w in ("normal", "forever", "wowf", "hardcore", "ruleset", "solo"))]
        print(f"  {ns('dynamic', flavor)}: HTTP {status}, {len(realms)} realms; ones that look relevant: {', '.join(odd) or 'none'}")

    print("\n== 3. How a Forever character could be addressed")
    full, spaced = f"{FIRST}-{LAST}", urllib.parse.quote(f"{FIRST} {LAST}")
    paths = [f"/profile/wow/character/{full}", f"/profile/wow/character/{spaced}", f"/profile/wow/character/{FIRST}{LAST}",
             f"/profile/wow/character/normal/{full}", f"/profile/wow/character/forever/{full}", f"/profile/wow/character/{REGION}/{full}",
             f"/profile/wow/character/{FIRST}/{LAST}", f"/profile/wow/character/{LAST}/{FIRST}",
             f"/profile/wow/character/{CHAR_ID}", f"/profile/wow/character/normal/{CHAR_ID}", f"/profile/wow/character/id/{CHAR_ID}",
             f"/profile/wow/forever/character/{full}", f"/profile/forever/character/{full}", f"/profile/wow/character/1/{full}"]
    found = None
    for flavor in (FOREVER, BOGUS):
        for path in paths:
            status, data = get(tok, path, ns("profile", flavor))
            ok = status == 200 and is_him(data)
            print(f"  {ns('profile', flavor)}  {path}: HTTP {status}{reason(data) if status != 200 else who(data)}{'  <-- him' if ok else ('  (someone else, ignored)' if status == 200 else '')}")
            if ok and not found:
                found = (flavor, path, data)
        if found:
            break
    print("  For comparison, a character that certainly doesn't exist in a real version:")
    status, data = get(tok, "/profile/wow/character/dreamscythe/zzqqxxnobody", ns("profile", KNOWN))
    print(f"  {ns('profile', KNOWN)}  /profile/wow/character/dreamscythe/zzqqxxnobody: HTTP {status}{reason(data)}")

    print("\n== 4. His guild, addressed the same ways")
    for path in (f"/data/wow/guild/normal/{GUILD}", f"/data/wow/guild/{GUILD}", f"/data/wow/guild/forever/{GUILD}", f"/data/wow/guild/normal/{GUILD}/roster"):
        status, data = get(tok, path, ns("profile", FOREVER))
        print(f"  {ns('profile', FOREVER)}  {path}: HTTP {status}{reason(data) if status != 200 else ' ' + repr((data or {}).get('name'))}")

    if not found:
        print("\nRESULT: Blizzard's API did not return Bonita Bluehair at any address tried.")
        return 2

    flavor, path, summary = found
    profile_ns = ns("profile", flavor)
    save("summary", summary)
    results.append(("character summary", profile_ns, 200))
    print(f"\n== 5. Found him: {path} in {profile_ns}")
    for k in ("name", "level", "last_login_timestamp", "equipped_item_level", "average_item_level", "experience"):
        if k in summary:
            print(f"  {k}: {summary[k]!r}")
    for k in ("realm", "race", "character_class", "active_spec", "faction", "gender", "guild"):
        x = summary.get(k)
        if isinstance(x, dict):
            print(f"  {k}: {x.get('name')!r}" + (f" (slug {x.get('slug')})" if x.get("slug") else "") + (f" [{x.get('type')}]" if x.get("type") else ""))
    print("  shape:")
    shape(summary, 1)

    print("\n== 6. The other endpoints")
    for sub in SUB:
        status, data = get(tok, f"{path}/{sub}", profile_ns, sub)
        print(f"\n  -- {sub}: HTTP {status}{reason(data) if status != 200 else ''}")
        if status != 200 or not isinstance(data, dict):
            continue
        save(sub, data)
        if sub == "equipment":
            for it in data.get("equipped_items") or []:
                print(f"    {((it.get('slot') or {}).get('name') or '?'):<12} {it.get('item', {}).get('id')!s:<8} {it.get('name')!r} quality={((it.get('quality') or {}).get('type'))} level={((it.get('level') or {}).get('value'))} inv={((it.get('inventory_type') or {}).get('name'))}")
            print("    shape of one item:")
            shape((data.get("equipped_items") or [{}])[0], 2, budget=[40])
        elif sub == "character-media":
            for a in data.get("assets") or []:
                print(f"    asset {a.get('key')}: {a.get('value')}")
            shape({k: v for k, v in data.items() if k != "assets"}, 2, budget=[20])
        else:
            shape(data, 2)

    print("\n== 7. Guild roster")
    href = ((summary.get("guild") or {}).get("key") or {}).get("href")
    if not href:
        print("  The summary names no guild.")
    else:
        base = href.split("?")[0]
        gns = (urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("namespace") or [profile_ns])[0]
        status, data = get(tok, base + "/roster", gns, "guild roster")
        print(f"  {base.split('.com', 1)[-1]}/roster in {gns}: HTTP {status}{reason(data) if status != 200 else ''}")
        members = ((data or {}).get("members") or []) if isinstance(data, dict) else []
        print(f"  members: {len(members)}")
        # Only his own entry is kept: the other members are other people's characters.
        save("guild-roster", {"member_count": len(members), "members": [m for m in members if (m.get("character") or {}).get("slug") == f"{FIRST}-{LAST}"]})
        for m in members:
            c = m.get("character") or {}
            if str(c.get("name") or "").lower().startswith(FIRST):
                print(f"  him: name {c.get('name')!r}, level {c.get('level')}, rank {m.get('rank')}")
        if members:
            print("  shape of one member:")
            shape(members[0], 2, budget=[30])

    print("\n== Summary")
    for label, namespace, status in results:
        print(f"  {label:<26} {namespace:<22} HTTP {status}")
    print(f"\nRESULT: Bonita Bluehair answers at {path} in {profile_ns}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
