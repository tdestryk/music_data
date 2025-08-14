# youtube_stats_extended.py
import os, time, json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
BASE = "https://www.googleapis.com/youtube/v3"

MAP_PATH = Path("youtube_channels.csv")
CHAN_CSV = Path("youtube_channel_stats.csv")
VID_CSV  = Path("youtube_video_stats.csv")
ARCHIVE_DIR = Path("archive")
RUNS_LOG = Path("runs.log")

MAX_RESULTS_PER_CHANNEL = 5   # how many latest videos per channel to capture
RETENTION_DAYS = 90           # keep last 90 days, older -> archive/

def yt_get(endpoint: str, params: dict):
    """GET helper with simple retry/backoff for 429/5xx."""
    if not API_KEY:
        raise RuntimeError("Missing YOUTUBE_API_KEY (set in .env or GitHub Secret).")
    params = dict(params or {})
    params["key"] = API_KEY
    url = f"{BASE}/{endpoint}"
    for attempt in range(5):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s...
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()

def load_channel_map() -> pd.DataFrame:
    if MAP_PATH.exists():
        df = pd.read_csv(MAP_PATH)
    else:
        df = pd.DataFrame(columns=["artist_name", "channel_id", "preferred"])
    return df

def save_channel_map(df: pd.DataFrame):
    df.to_csv(MAP_PATH, index=False)

def search_channel_id(artist_name: str) -> str | None:
    """If channel_id missing, search once and pick first result."""
    data = yt_get("search", {
        "part": "snippet",
        "q": f"{artist_name} official",
        "type": "channel",
        "maxResults": 5,
    })
    items = data.get("items", [])
    if not items:
        return None
    return items[0]["snippet"]["channelId"]

def fetch_channel_stats(channel_id: str):
    data = yt_get("channels", {
        "part": "snippet,statistics",
        "id": channel_id
    })
    items = data.get("items", [])
    if not items:
        return None
    it = items[0]
    sn = it["snippet"]
    st = it["statistics"]
    return {
        "channel_id": channel_id,
        "title": sn.get("title"),
        "subs": int(st.get("subscriberCount", 0)),
        "views": int(st.get("viewCount", 0)),
        "video_count": int(st.get("videoCount", 0)),
    }

def fetch_latest_videos(channel_id: str, n: int):
    search = yt_get("search", {
        "part": "snippet",
        "channelId": channel_id,
        "order": "date",
        "type": "video",
        "maxResults": n
    })
    items = search.get("items", [])
    if not items:
        return []

    video_ids = [it["id"]["videoId"] for it in items]
    if not video_ids:
        return []

    vid = yt_get("videos", {
        "part": "statistics,snippet",
        "id": ",".join(video_ids)
    })
    out = []
    for it in vid.get("items", []):
        sn = it["snippet"]
        st = it.get("statistics", {})
        out.append({
            "video_id": it.get("id"),
            "title": sn.get("title"),
            "published_at": sn.get("publishedAt"),
            "views": int(st.get("viewCount", 0)) if st.get("viewCount") is not None else None,
            "likes": int(st.get("likeCount", 0)) if st.get("likeCount") is not None else None,
            "comments": int(st.get("commentCount", 0)) if st.get("commentCount") is not None else None,
        })
    return out

def append_df(path: Path, df: pd.DataFrame):
    if df.empty:
        return
    header = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    # small dedup guard: drop exact duplicate rows
    df = df.drop_duplicates()
    df.to_csv(path, mode="a", header=header, index=False)

def cap_and_archive(path: Path, timestamp_col: str):
    """Keep only last N days; move older rows to archive/."""
    if not path.exists():
        return 0, 0
    df = pd.read_csv(path, engine="python", on_bad_lines="skip")
    if df.empty or timestamp_col not in df.columns:
        return 0, 0
    df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors="coerce", utc=True)
    df = df.dropna(subset=[timestamp_col])
    cutoff = pd.Timestamp.now(tz=timezone.utc) - timedelta(days=RETENTION_DAYS)

    keep = df[df[timestamp_col] >= cutoff]
    old  = df[df[timestamp_col] < cutoff]

    if not old.empty:
        ARCHIVE_DIR.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        arch = ARCHIVE_DIR / f"{path.stem}_{stamp}.csv"
        # append if file exists so we don’t lose older archives on repeated runs same day
        mode = "a" if arch.exists() else "w"
        old.to_csv(arch, index=False, header=not arch.exists(), mode=mode)

    keep.to_csv(path, index=False)
    return len(keep), len(old)

def log_run(status: str, rows_channels: int, rows_videos: int, dur_s: float):
    line = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "component": "youtube",
        "status": status,
        "rows_channels": rows_channels,
        "rows_videos": rows_videos,
        "duration_s": round(dur_s, 3),
    }
    existing = RUNS_LOG.read_text(encoding="utf-8") if RUNS_LOG.exists() else ""
    RUNS_LOG.write_text(existing + ("" if not existing else "\n") + json.dumps(line), encoding="utf-8")

def main(dry_run: bool = False):
    t0 = time.time()

    mapping = load_channel_map()
    if mapping.empty:
        raise RuntimeError("youtube_channels.csv is empty or missing.")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    channel_rows, video_rows = [], []

    for artist in mapping["artist_name"].unique().tolist():
        row = mapping[mapping["artist_name"] == artist].iloc[0]
        ch_id = str(row.get("channel_id") or "").strip()
        if not ch_id:
            ch_id = search_channel_id(artist)
            if ch_id:
                mapping.loc[mapping["artist_name"] == artist, "channel_id"] = ch_id
                save_channel_map(mapping)
            else:
                print(f"⚠️  No channel found for {artist}")
                continue

        ch = fetch_channel_stats(ch_id)
        if not ch:
            print(f"⚠️  Stats not found for {artist} ({ch_id})")
            continue

        # channel stat snapshot
        channel_rows.append({
            "artist_name": artist,
            "channel_id": ch_id,
            "channel_title": ch["title"],
            "subs": ch["subs"],
            "views": ch["views"],
            "video_count": ch["video_count"],
            "timestamp": now
        })

        # a few latest videos
        vids = fetch_latest_videos(ch_id, MAX_RESULTS_PER_CHANNEL)
        for v in vids:
            video_rows.append({
                "artist_name": artist,
                "channel_id": ch_id,
                "video_id": v["video_id"],
                "title": v["title"],
                "published_at": v["published_at"],
                "views": v["views"],
                "likes": v["likes"],
                "comments": v["comments"],
                "timestamp": now
            })

    chans_rows = len(channel_rows)
    vids_rows  = len(video_rows)

    if dry_run:
        print(f"[dry-run] channel rows: {chans_rows}, video rows: {vids_rows}")
    else:
        append_df(CHAN_CSV, pd.DataFrame(channel_rows))
        append_df(VID_CSV,  pd.DataFrame(video_rows))

        # retention + archive
        cap_and_archive(CHAN_CSV, "timestamp")
        cap_and_archive(VID_CSV,  "timestamp")

    dur = time.time() - t0
    status = "ok" if (chans_rows + vids_rows) > 0 else "no-op"
    log_run(status, chans_rows, vids_rows, dur)

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="run without writing CSVs")
    args = p.parse_args()
    main(dry_run=args.dry_run)
