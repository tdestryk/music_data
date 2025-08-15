# fetch_youtube.py
from __future__ import annotations

import os
import sys
import time
import json
import math
import pandas as pd
import requests
from dotenv import load_dotenv
load_dotenv(".env")  # <— explicit path so it works everywhere

OUT_CSV = "youtube_stats.csv"
LINKS_CSV = "artist_links.csv"

API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
BASE = "https://www.googleapis.com/youtube/v3"

def load_links() -> pd.DataFrame:
    if not os.path.exists(LINKS_CSV):
        print(f"{LINKS_CSV} missing.")
        return pd.DataFrame(columns=["artist_name", "youtube_channel_id"])
    df = pd.read_csv(LINKS_CSV)
    need = ["artist_name", "youtube_channel_id"]
    for n in need:
        if n not in df.columns:
            raise ValueError(f"{LINKS_CSV} must contain column '{n}'")
    df["youtube_channel_id"] = df["youtube_channel_id"].astype(str).str.strip()
    df = df[df["youtube_channel_id"].str.startswith("UC", na=False)].copy()
    return df[["artist_name", "youtube_channel_id"]].drop_duplicates()

def yt_channels_stats(ids: list[str]) -> tuple[list[dict], dict]:
    params = {
        "part": "statistics,snippet",
        "id": ",".join(ids),
        "key": API_KEY,
        "maxResults": 50,
    }
    url = f"{BASE}/channels"
    res = requests.get(url, params=params, timeout=30)
    meta = {"status": res.status_code}
    if res.status_code == 403:
        # Quota exceeded / forbidden – don’t fail the workflow
        try:
            meta["error"] = res.json()
        except Exception:
            meta["error"] = {"message": "HTTP 403"}
        print("[WARN] YouTube API 403 (quota/forbidden). Skipping write.", file=sys.stderr)
        return [], meta
    res.raise_for_status()
    data = res.json()
    rows = []
    now = pd.Timestamp.now(tz="UTC").floor("s")
    for item in data.get("items", []):
        ch_id = item.get("id")
        snippet = item.get("snippet", {})
        stats   = item.get("statistics", {})
        rows.append({
            "timestamp": now.isoformat(),
            "artist_name": snippet.get("title", ""),  # will overwrite with link name on merge
            "channel_id": ch_id,
            "subscribers": int(stats.get("subscriberCount", 0) or 0),
            "views": int(stats.get("viewCount", 0) or 0),
            "thumb_url": (snippet.get("thumbnails", {}).get("high", {}) or {}).get("url", ""),
        })
    return rows, meta

def append_rows(new_rows: list[dict]) -> int:
    if not new_rows:
        return 0
    new_df = pd.DataFrame(new_rows)
    if os.path.exists(OUT_CSV):
        old = pd.read_csv(OUT_CSV)
        # normalize
        for c in ("timestamp",):
            if c in old.columns:
                old[c] = pd.to_datetime(old[c], utc=True, errors="coerce").dt.tz_convert("UTC")
        all_df = pd.concat([old, new_df], ignore_index=True)
    else:
        all_df = new_df
    # de-dup per artist/minute
    all_df["timestamp"] = pd.to_datetime(all_df["timestamp"], utc=True, errors="coerce").dt.floor("min")
    all_df = (all_df
              .sort_values(["artist_name", "timestamp"])
              .drop_duplicates(subset=["artist_name", "timestamp"], keep="last"))
    all_df.to_csv(OUT_CSV, index=False)
    return len(new_rows)

def main():
    if not API_KEY:
        print("Set YOUTUBE_API_KEY in env.")
        return

    links = load_links()
    if links.empty:
        print("No channel IDs found in artist_links.csv")
        return

    ch_ids = links["youtube_channel_id"].tolist()
    # Batch once (≤50)
    new_rows, meta = yt_channels_stats(ch_ids)
    # Map API titles back to your canonical artist_name from CSV
    id_to_name = dict(zip(links["youtube_channel_id"], links["artist_name"]))
    for r in new_rows:
        r["artist_name"] = id_to_name.get(r["channel_id"], r["artist_name"])

    # Warn if API ignored some IDs (quota sometimes returns partial)
    returned = {r["channel_id"] for r in new_rows}
    missing  = [f"- {id_to_name[c]}: {c}" for c in ch_ids if c not in returned]
    if missing:
        print("[WARN] These channel IDs were requested but not returned by the API:")
        for line in missing:
            print(" ", line)

    wrote = append_rows(new_rows)
    print(f"Wrote {wrote} new rows; {sum(1 for _ in open(OUT_CSV)) - 1 if os.path.exists(OUT_CSV) else 0} total -> {OUT_CSV}")

if __name__ == "__main__":
    main()
