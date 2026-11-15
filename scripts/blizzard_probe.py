#!/usr/bin/env python3
"""Find out what Blizzard's official API offers for Bonita Bluehair in WoW: Forever.

Run by the "Blizzard API probe" workflow (Actions tab -> Blizzard API probe -> Run workflow), which passes the API
client's ID and secret from the repository's Actions secrets. It gets a token, tries the likely namespaces for the
character, and for the first one that answers prints the status and the shape of every endpoint the tracker would
need, so scripts/update.py can be rewritten against real responses.

It prints public game data only: never the token, the client ID or the secret. It makes about 30 requests.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REGION = "us"
HOST = f"https://{REGION}.api.blizzard.com"
UA = "christmas-bet-tracker/1.0 (+https://bonitabluehair.com)"
# The namespace is "profile-<flavor>-us" (plain "profile-us" for retail). classicarmory.gg, which read this same
# API, called its flavors classic, classic1x, classicann and forever, so "forever" is the first guess.
FLAVORS = ["forever", "classic1x", "classicann", "classic", ""]
REALMS = ["normal"]  # the Armory showed his realm as "Normal"
NAMES = ["bonita-bluehair", "bonita bluehair", "bonitabluehair", "bonita"]
SUB = ["status", "equipment", "character-media", "statistics", "achievements/statistics", "professions",
       "reputations", "specializations", "pvp-summary"]
results = []


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
    return f" ({data.get('code')}: {data.get('detail') or data.get('type')})" if isinstance(data, dict) and (data.get("detail") or data.get("code")) else ""


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
    tok = token()

    print("\n== 1. Realm lists by namespace")
    realms_by_flavor = {}
    for flavor in FLAVORS:
        status, data = get(tok, "/data/wow/realm/index", ns("dynamic", flavor), "realm index")
        realms = [(r.get("slug"), r.get("name")) for r in (data or {}).get("realms", [])] if isinstance(data, dict) else []
        realms_by_flavor[flavor] = realms
        print(f"  {ns('dynamic', flavor)}: HTTP {status}{reason(data)}, {len(realms)} realms" + (": " + ", ".join(f"{s} ({n})" for s, n in realms[:14]) + (" ..." if len(realms) > 14 else "") if realms else ""))

    print("\n== 2. Looking for the character")
    found = None
    for flavor in FLAVORS:
        listed = realms_by_flavor.get(flavor) or []
        slugs = list(REALMS) + [s for s, n in listed if s and s not in REALMS and (len(listed) <= 6 or "normal" in (n or "").lower())]
        for realm in slugs:
            for name in NAMES:
                path = f"/profile/wow/character/{urllib.parse.quote(realm)}/{urllib.parse.quote(name.lower())}"
                status, data = get(tok, path, ns("profile", flavor))
                print(f"  {ns('profile', flavor)}  {realm}/{name!r}: HTTP {status}{reason(data)}")
                if status == 200 and isinstance(data, dict):
                    found = (flavor, path, data)
                    break
            if found:
                break
        if found:
            break
    if not found:
        print("\nRESULT: no namespace returned the character. Blizzard's API does not expose him to this client under any name tried.")
        return 2

    flavor, path, summary = found
    profile_ns = ns("profile", flavor)
    results.append(("character summary", profile_ns, 200))
    print(f"\n== 3. Found him: {path} in {profile_ns}")
    for k in ("name", "level", "last_login_timestamp", "equipped_item_level", "average_item_level", "experience"):
        if k in summary:
            print(f"  {k}: {summary[k]!r}")
    for k in ("realm", "race", "character_class", "active_spec", "faction", "gender", "guild"):
        x = summary.get(k)
        if isinstance(x, dict):
            print(f"  {k}: {x.get('name')!r}" + (f" (slug {x.get('slug')})" if x.get("slug") else "") + (f" [{x.get('type')}]" if x.get("type") else ""))
    print("  shape:")
    shape(summary, 1)

    print("\n== 4. The other endpoints")
    for sub in SUB:
        status, data = get(tok, f"{path}/{sub}", profile_ns, sub)
        print(f"\n  -- {sub}: HTTP {status}{reason(data)}")
        if status != 200 or not isinstance(data, dict):
            continue
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

    print("\n== 5. Guild roster")
    guild = summary.get("guild") or {}
    href = (guild.get("key") or {}).get("href")
    if not href:
        print("  The summary names no guild.")
    else:
        base = href.split("?")[0]
        gns = (urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("namespace") or [profile_ns])[0]
        status, data = get(tok, base + "/roster", gns, "guild roster")
        print(f"  {base.split('.com', 1)[-1]}/roster in {gns}: HTTP {status}{reason(data)}")
        members = (data or {}).get("members") or [] if isinstance(data, dict) else []
        print(f"  members: {len(members)}")
        me = [m for m in members if (m.get("character") or {}).get("name", "").lower().startswith("bonita")]
        for m in me:
            c = m["character"]
            print(f"  him: name {c.get('name')!r}, level {c.get('level')}, rank {m.get('rank')}")
        if members:
            print("  shape of one member:")
            shape(members[0], 2, budget=[30])

    print("\n== Summary")
    for label, namespace, status in results:
        if label != "realm index":
            print(f"  {label:<26} {namespace:<22} HTTP {status}")
    print(f"\nRESULT: the character answers in {profile_ns}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
