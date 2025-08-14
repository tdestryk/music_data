from __future__ import annotations

import os
import sys
import time
from typing import Dict, List

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise EnvironmentError("Set YOUTUBE_API_KEY in your .env")

LINKS_CSV = "artist_links.csv"
OUT_CSV = "youtube_stats.csv"
API_URL = "https://www.googleapis.com/youtube/v3/channels"

def utc_now() -> pd.Timestamp:
    now = pd.Timestamp.utcnow()
    if now.tzinfo is None:
        return now.tz_localize("UTC")
    return now.tz_convert("UTC")

def read_artist_links(path: str = LINKS_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "artist_name" not in df.columns or "youtube_channel_id" not in df.columns:
        raise ValueError("artist_links.csv must include 'artist_name' and 'youtube_channel_id'")
    df["artist_name"] = df["artist_name"].astype(str).str.strip()
    df["youtube_channel_id"] = df["youtube_channel_id"].astype(str).str.strip()
    # Only UC… channel ids are valid here
    df = df[df["youtube_channel_id"].str.startswith("UC")]
    df = df[df["youtube_channel_id"].str.len() > 0]
    return df[["artist_name", "youtube_channel_id"]].drop_duplicates()

def chunk(ids: List[str], n: int) -> List[List[str]]:
    return [ids[i:i+n] for i in range(0, len(ids), n)]

def fetch_channels_stats(api_key: str, ids: List[str]) -> Dict[str, Dict]:
    """Return cid -> {subscribers, views, thumb_url}."""
    result: Dict[str, Dict] = {}
    for group in chunk(ids, 50):
        params = {"part": "snippet,statistics", "id": ",".join(group), "key": api_key}
        r = requests.get(API_URL, params=params, timeout=30)
        if r.status_code != 200:
            print(f"[YouTube] HTTP {r.status_code} -> {r.text[:200]}", file=sys.stderr)
            continue
        data = r.json()
        for item in data.get("items", []):
            cid = item.get("id", "")
            stats = item.get("statistics", {}) or {}
            snip = item.get("snippet", {}) or {}
            thumbs = (snip.get("thumbnails") or {}).get("high") or snip.get("thumbnails", {}).get("default") or {}
            result[cid] = {
                "subscribers": int(stats.get("subscriberCount", 0) or 0),
                "views": int(stats.get("viewCount", 0) or 0),
                "thumb_url": thumbs.get("url", ""),
            }
        time.sleep(0.2)
    return result

def main() -> None:
    links = read_artist_links()
    if links.empty:
        print("No artists with a UC… youtube_channel_id found in artist_links.csv")
        return

    id_list = links["youtube_channel_id"].tolist()
    stats_by = fetch_channels_stats(YOUTUBE_API_KEY, id_list)

    missing = sorted(set(id_list) - set(stats_by.keys()))
    if missing:
        print("[WARN] These channel IDs were requested but not returned by the API:")
        for m in missing:
            name = links.loc[links["youtube_channel_id"] == m, "artist_name"].iloc[0]
            print(f"  - {name}: {m}")

    ts = utc_now()
    rows = []
    for _, r in links.iterrows():
        cid = r["youtube_channel_id"]
        s = stats_by.get(cid, {"subscribers": 0, "views": 0, "thumb_url": ""})
        rows.append({
            "timestamp": ts.isoformat(timespec="seconds"),
            "artist_name": r["artist_name"],
            "channel_id": cid,
            "subscribers": s["subscribers"],
            "views": s["views"],
            "thumb_url": s["thumb_url"],
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
