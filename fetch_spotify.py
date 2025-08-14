from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Iterable, List

import pandas as pd
import requests
from dotenv import load_dotenv

# --- env / constants ---
load_dotenv()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

LINKS_CSV = "artist_links.csv"
OUT_CSV = "spotify_stats.csv"
SPOTIFY_API = "https://api.spotify.com/v1"

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    raise EnvironmentError("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your .env")

# --- helpers ---
def utc_now() -> pd.Timestamp:
    now = pd.Timestamp.utcnow()
    if now.tzinfo is None:
        return now.tz_localize("UTC")
    return now.tz_convert("UTC")

def batched(it: Iterable[Any], n: int) -> Iterable[List[Any]]:
    buf: List[Any] = []
    for x in it:
        buf.append(x)
        if len(buf) == n:
            yield buf
            buf = []
    if buf:
        yield buf

def get_token() -> str:
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def extract_spotify_id(val: str) -> str | None:
    if not isinstance(val, str):
        return None
    s = val.strip()
    if re.fullmatch(r"[0-9A-Za-z]{22}", s):
        return s
    m = re.search(r"spotify\.com/artist/([0-9A-Za-z]{22})", s)
    return m.group(1) if m else None

def read_artist_links(path: str = LINKS_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    # normalize headers (case-insensitive)
    lc = {c.lower(): c for c in df.columns}
    artist_col = lc.get("artist_name") or lc.get("artist")
    sp_id_col = lc.get("spotify_id")
    sp_url_col = lc.get("spotify_url")
    if not artist_col:
        raise ValueError("artist_links.csv needs an 'artist_name' column")
    if not (sp_id_col or sp_url_col):
        raise ValueError("artist_links.csv needs 'spotify_id' or 'spotify_url'")

    # Build spotify_id column
    if sp_id_col:
        df["spotify_id"] = df[sp_id_col].apply(extract_spotify_id)
    else:
        df["spotify_id"] = df[sp_url_col].apply(extract_spotify_id)

    keep = df["spotify_id"].notna()
    df = df.loc[keep, [artist_col, "spotify_id"]].rename(columns={artist_col: "artist_name"})
    df["artist_name"] = df["artist_name"].astype(str).str.strip()
    df = df.drop_duplicates(subset=["artist_name", "spotify_id"])
    return df

def get_artists(token: str, ids: List[str]) -> Dict[str, Dict]:
    headers = {"Authorization": f"Bearer {token}"}
    out: Dict[str, Dict] = {}
    for group in batched(ids, 50):
        r = requests.get(f"{SPOTIFY_API}/artists", params={"ids": ",".join(group)}, headers=headers, timeout=20)
        r.raise_for_status()
        for a in r.json().get("artists", []):
            if a and a.get("id"):
                out[a["id"]] = a
        time.sleep(0.1)
    return out

def avg_top_track_popularity(token: str, artist_id: str, market: str = "US") -> float:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{SPOTIFY_API}/artists/{artist_id}/top-tracks", params={"market": market}, headers=headers, timeout=20)
    if r.status_code == 429:
        time.sleep(int(r.headers.get("Retry-After", "1")))
        r = requests.get(f"{SPOTIFY_API}/artists/{artist_id}/top-tracks", params={"market": market}, headers=headers, timeout=20)
    r.raise_for_status()
    tracks = r.json().get("tracks", []) or []
    if not tracks:
        return 0.0
    pops = [int(t.get("popularity", 0) or 0) for t in tracks]
    return round(sum(pops) / len(pops), 1)

# --- main ---
def main() -> None:
    links = read_artist_links()
    if links.empty:
        print("No artists with spotify_id found in artist_links.csv")
        return

    token = get_token()
    info = get_artists(token, links["spotify_id"].tolist())

    ts = utc_now()
    rows: List[Dict[str, Any]] = []
    for _, r in links.iterrows():
        aid = r["spotify_id"]
        a = info.get(aid)
        if not a:
            rows.append({
                "timestamp": ts.isoformat(),
                "artist_name": r["artist_name"],
                "spotify_id": aid,
                "followers": None,
                "popularity": None,
                "genres": None,
                "avg_top_track_pop": None,
            })
            continue

        try:
            avg_pop = avg_top_track_popularity(token, aid)
        except Exception:
            avg_pop = 0.0

        rows.append({
            "timestamp": ts.isoformat(),
            "artist_name": a.get("name") or r["artist_name"],
            "spotify_id": aid,
            "followers": a.get("followers", {}).get("total"),
            "popularity": a.get("popularity"),
            "genres": ", ".join(a.get("genres", []) or []),
            "avg_top_track_pop": avg_pop,
        })

    if not rows:
        print("No rows fetched.")
        return

    new = pd.DataFrame(rows)
    new["timestamp"] = pd.to_datetime(new["timestamp"], utc=True)
    new["ts_min"] = new["timestamp"].dt.floor("min")

    if os.path.exists(OUT_CSV):
        old = pd.read_csv(OUT_CSV, parse_dates=["timestamp"])
        old["ts_min"] = pd.to_datetime(old["timestamp"], utc=True).dt.floor("min")
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new

    out = (
        out.sort_values(["artist_name", "timestamp"])
           .drop_duplicates(["artist_name", "ts_min"], keep="last")
           .drop(columns=["ts_min"])
    )
    out.to_csv(OUT_CSV, index=False)
    print(f"Wrote {len(new)} new rows; {len(out)} total -> {OUT_CSV}")

if __name__ == "__main__":
    main()
