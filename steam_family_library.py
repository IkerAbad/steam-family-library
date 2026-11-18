#!/usr/bin/env python3
"""
Export your full Steam library -- your own games plus every game shared with
you through Steam Families -- to JSON and CSV.

Steam's well-known IPlayerService/GetOwnedGames endpoint only ever returns
games you personally own; family-shared titles are invisible to it. This
script uses IFamilyGroupsService/GetSharedLibraryApps instead, which returns
the merged family library and records which member owns each title.

Requires Python 3.8+. No third-party dependencies.

See README.md for how to obtain a token.

    export STEAM_WEBAPI_TOKEN='eyJ0eXAi...'
    python3 steam_family_library.py

MIT licensed.
"""

import argparse
import base64
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.steampowered.com"

# Values Steam returns in the `exclude_reason` field. 0 means the game is
# shareable and playable by you right now.
EXCLUDE_REASONS = {
    0: "",
    1: "excluded by owner",
    2: "not eligible for sharing",
    3: "region or DRM restricted",
}


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def api_get(iface_method, params):
    """Call a Steam web API GET endpoint and return its `response` object."""
    url = f"{API}/{iface_method}/?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        url, headers={"User-Agent": "steam-family-library/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        hint = ""
        if e.code in (401, 403):
            hint = "\n\nA 401/403 nearly always means the token expired. Grab a fresh one."
        die(f"{iface_method} returned HTTP {e.code}\n{body}{hint}")
    except urllib.error.URLError as e:
        die(f"could not reach the Steam API: {e.reason}")
    return payload.get("response", {})


def steamid_from_token(token):
    """The webapi_token is a JWT whose `sub` claim is the account's SteamID64."""
    parts = token.split(".")
    if len(parts) != 3:
        die("token does not look like a JWT -- copy only the webapi_token "
            "value, without surrounding quotes or whitespace")
    try:
        claims_b64 = parts[1] + "=" * (-len(parts[1]) % 4)  # restore padding
        claims = json.loads(base64.urlsafe_b64decode(claims_b64))
    except Exception:
        die("could not decode the token payload")

    exp = claims.get("exp")
    if exp and datetime.now(tz=timezone.utc).timestamp() > exp:
        die("that token has expired -- reload the token URL for a new one")

    steamid = claims.get("sub")
    if not steamid:
        die("token has no `sub` claim, so no SteamID could be read from it")
    return steamid


def day(epoch):
    """Steam's rt_* fields are unix seconds. 0 means never."""
    if not epoch:
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")


def fetch(token, include_free, include_non_games):
    steamid = steamid_from_token(token)

    fam = api_get(
        "IFamilyGroupsService/GetFamilyGroupForUser/v1",
        {
            "access_token": token,
            "steamid": steamid,
            "include_family_group_response": "true",
        },
    )
    group_id = fam.get("family_groupid")
    if not group_id or fam.get("is_not_member_of_any_group"):
        die("this account is not in a Steam Family group, so there is no "
            "shared library to read")

    group = fam.get("family_group", {})
    members = [m.get("steamid") for m in group.get("members", [])]
    print(f"SteamID64:    {steamid}")
    print(f"Family group: {group.get('name', '?')} ({group_id}), "
          f"{len(members)} members")

    # include_own folds your own games into the same list, so one call returns
    # the whole picture. include_excluded keeps titles the owner has withheld
    # from sharing, so you can see and filter them rather than silently
    # missing them.
    lib = api_get(
        "IFamilyGroupsService/GetSharedLibraryApps/v1",
        {
            "access_token": token,
            "family_groupid": group_id,
            "include_own": "true",
            "include_excluded": "true",
            "include_free": str(bool(include_free)).lower(),
            "include_non_games": str(bool(include_non_games)).lower(),
            "language": "english",
        },
    )
    apps = lib.get("apps", [])
    if not apps:
        die("the API returned zero apps -- the token may belong to a "
            "different account than expected")

    me = str(steamid)
    games = []
    for a in apps:
        owners = [str(o) for o in a.get("owner_steamids", [])]
        reason = a.get("exclude_reason", 0)
        games.append({
            "appid": a.get("appid"),
            "name": a.get("name", ""),
            "source": "own" if me in owners else "family",
            "owned_by_me": me in owners,
            "owner_steamids": owners,
            "playable": reason == 0,
            "exclude_reason": EXCLUDE_REASONS.get(reason, f"unknown ({reason})"),
            "playtime_minutes": a.get("rt_playtime", 0),
            "acquired": day(a.get("rt_time_acquired")),
            "last_played": day(a.get("rt_last_played")),
            "store_url": f"https://store.steampowered.com/app/{a.get('appid')}",
        })

    games.sort(key=lambda g: g["name"].lower())
    return {
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "steamid": steamid,
        "family_groupid": group_id,
        "family_name": group.get("name", ""),
        "members": members,
        "count": len(games),
        "games": games,
    }


CSV_COLUMNS = [
    "appid", "name", "source", "playable", "exclude_reason",
    "playtime_minutes", "acquired", "last_played", "store_url",
]


def write_csv(path, games):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(games)


def main():
    p = argparse.ArgumentParser(
        description="Export your Steam library including Family Sharing games."
    )
    p.add_argument("--json", default="library.json", help="JSON output path")
    p.add_argument("--csv", default="library.csv", help="CSV output path")
    p.add_argument("--include-free", action="store_true",
                   help="include free-to-play titles")
    p.add_argument("--include-non-games", action="store_true",
                   help="include tools, soundtracks, demos and similar")
    p.add_argument("--token", default=os.environ.get("STEAM_WEBAPI_TOKEN", ""),
                   help="webapi_token (defaults to $STEAM_WEBAPI_TOKEN)")
    args = p.parse_args()

    token = args.token.strip().strip("\"'")
    if not token:
        die("no token supplied. Set STEAM_WEBAPI_TOKEN or pass --token. "
            "See the README for how to get one.")

    data = fetch(token, args.include_free, args.include_non_games)
    games = data["games"]

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    write_csv(args.csv, games)

    mine = sum(1 for g in games if g["owned_by_me"])
    blocked = sum(1 for g in games if not g["playable"])
    print(f"\n{len(games)} games")
    print(f"  {mine} owned by you")
    print(f"  {len(games) - mine} from family sharing")
    print(f"  {blocked} not currently playable")
    print(f"\nwrote {args.json} and {args.csv}")


if __name__ == "__main__":
    main()
