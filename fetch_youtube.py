from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd
import requests

# ----------------------------
# Config / constants
# ----------------------------
LINKS_CSV = "artist_links.csv"
OUT_CSV = "youtube_stats.csv"
YT_API = "https://youtube.googleapis.com/youtube/v3/channels"
API_KEY = os.getenv("YOUTUBE_API_KEY")

# Fail fast if not configured (keeps Actions logs obvious)
if not API_KEY:
    print("Set YOUTUBE_API_KEY in env.")
    raise SystemExit(1)


# ----------------------------
# Helpers
# ----------------------------
def utc_now() -> pd.Timestamp:
    """Return a tz-aware UTC timestamp (works no matter what)."""
    now = pd.Timestamp.utcnow()  # naive
    return now.tz_localize("UTC")


def batched(it: Iterable[Any], n: int) -> Iterable[List[Any]]:
    buf: List[Any] = []
    for x in it:
        buf.append(x)
        if len(buf) == n:
            yield buf
            buf = []
    if buf:
        yield buf


UC_RE = re.compile(r"(?:^|/)(UC[0-9A-Za-z_-]{22})(?:$|[/?])")


def extract_uc_from_url(url: str | float | None) -> str | None:
    """Pull a UC… channel id from a /channel/UC… style URL if present."""
    if not isinstance(url, str):
        return None
    m = UC_RE.search(url.strip())
    return m.group(1) if m else None


def normalize_channel_id(row: pd.Series) -> str | None:
    """
    Prefer explicit youtube_channel_id.
    Fall back to extracting UC… from youtube_url if it’s a /channel/UC… URL.
    NOTE: We do NOT resolve @handles here to save quota — verify those in CSV.
    """
    cid = row.get("youtube_channel_id")
    if isinstance(cid, str) and cid.strip().startswith("UC"):
        return cid.strip()

    url = row.get("youtube_url")
    uc = extract_uc_from_url(url)
    if uc:
        return uc

    return None


def read_artist_links(path: str = LINKS_CSV) -> pd.DataFrame:
    """Load artist list and yield (artist_name, channel_id) rows we can actually fetch."""
    df = pd.read_csv(path)

    # Normalize columns in a case-insensitive way
    cols = {c.lower(): c for c in df.columns}
    artist_col = cols.get("artist_name") or cols.get("artist")
    yc_col = cols.get("youtube_channel_id")
    yu_col = cols.get("youtube_url")

    if not artist_col:
        raise ValueError("artist_links.csv must include 'artist_name'")
    if not (yc_col or yu_col):
        raise ValueError("artist_links.csv must include 'youtube_channel_id' or 'youtube_url'")

    # Build a normalized frame
    keep_cols = [artist_col]
    if yc_col:
        keep_cols.append(yc_col)
    if yu_col:
        keep_cols.append(yu_col)

    slim = df[keep_cols].rename(columns={artist_col: "artist_name"})
    slim["artist_name"] = slim["artist_name"].astype(str).str.strip()

    # Compute a final channel_id column
    slim["channel_id"] = slim.apply(normalize_channel_id, axis=1)

    return slim


def yt_fetch_channels(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch statistics + snippet for up to 50 channels at once.
    Returns dict keyed by channelId with {subscribers, viewCount, thumb_url, title}.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not ids:
        return out

    # YouTube allows up to 50 IDs per call
    for group in batched(ids, 50):
        params = {
            "part": "statistics,snippet",
            "id": ",".join(group),
            "key": API_KEY,
            # fields helps a bit with quota
            "fields": "items(id,snippet(title,thumbnails/default/url),statistics(subscriberCount,viewCount))",
        }
        r = requests.get(YT_API, params=params, timeout=30)
        # Be graceful on quota errors in Actions
        if r.status_code == 403:
            # Print a concise reason if provided
            try:
                msg = r.json()
            except Exception:
                msg = {"error": "HTTP 403"}
            print("[WARN] 403 from YouTube API on batch; sleeping and continuing. Detail:", msg)
            time.sleep(2.0)
            continue

        r.raise_for_status()
        data = r.json()

        for item in data.get("items", []):
            cid = item.get("id")
            stats = item.get("statistics", {}) or {}
            snip = item.get("snippet", {}) or {}
            out[cid] = {
                "title": snip.get("title"),
                "subscribers": int(stats.get("subscriberCount", 0) or 0),
                "views": int(stats.get("viewCount", 0) or 0),
                "thumb_url": (((snip.get("thumbnails") or {}).get("default") or {}).get("url")) or "",
            }

        # Be polite in CI
        time.sleep(0.15)

    return out


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    links = read_artist_links()

    # Split: resolvable vs missing
    have = links[links["channel_id"].notna()].copy()
    missing = links[links["channel_id"].isna()].copy()

    if not have.empty:
        # De-dup by artist/channel
        have = have.drop_duplicates(subset=["artist_name", "channel_id"], keep="last")
    else:
        print("No resolvable YouTube channel IDs in artist_links.csv")
        # still show what’s missing for the user
        if not missing.empty:
            print("\n[WARN] Missing channel IDs (please add a UC… id or a /channel/UC… URL):")
            for _, r in missing.iterrows():
                print(f"  - {r['artist_name']}")
        return

    # Fetch
    id_list = have["channel_id"].tolist()
    info = yt_fetch_channels(id_list)

    # Warn if API returned fewer channels than requested
    if info and len(info) < len(id_list):
        returned = set(info.keys())
        print("[WARN] These channel IDs were requested but not returned by the API:")
        for _, r in have.iterrows():
            cid = r["channel_id"]
            if cid not in returned:
                print(f"  - {r['artist_name']}: {cid}")

    # Build new rows
    ts = utc_now()
    rows: List[Dict[str, Any]] = []
    for _, r in have.iterrows():
        cid = r["channel_id"]
        a = info.get(cid)
        if not a:
            # Keep a placeholder so your table shows the artist and we can see what's missing
            rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "artist_name": r["artist_name"],
                    "channel_id": cid,
                    "subscribers": None,
                    "views": None,
                    "thumb_url": "",
                }
            )
            continue

        rows.append(
            {
                "timestamp": ts.isoformat(),
                "artist_name": r["artist_name"],
                "channel_id": cid,
                "subscribers": a["subscribers"],
                "views": a["views"],
                "thumb_url": a.get("thumb_url", ""),
            }
        )

    if not rows:
        print("No rows fetched.")
        return

    new = pd.DataFrame(rows)

    # Robust timestamp parsing (handles ISO, with/without micros)
    new["timestamp"] = pd.to_datetime(new["timestamp"], utc=True, errors="coerce")
    new["ts_min"] = new["timestamp"].dt.floor("min")

    # Merge with existing, dedupe to 1 row per artist per minute
    if os.path.exists(OUT_CSV):
        old = pd.read_csv(OUT_CSV)
        # Make parsing robust for old content
        old["timestamp"] = pd.to_datetime(old["timestamp"], utc=True, errors="coerce")
        old["ts_min"] = old["timestamp"].dt.floor("min")
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new

    out = (
        out.sort_values(["artist_name", "timestamp"])
           .drop_duplicates(["artist_name", "ts_min"], keep="last")
           .drop(columns=["ts_min"])
    )
    out.to_csv(OUT_CSV, index=False)

    # Console summary
    print(f"Wrote {len(new)} new rows; {len(out)} total -> {OUT_CSV}")

    # Guidance for unresolved channels
    if not missing.empty:
        print("\n[INFO] Skipped artists without a resolvable channel id:")
        for _, r in missing.iterrows():
            print(f"  - {r['artist_name']} (add youtube_channel_id or a /channel/UC… URL)")

    # Guidance for placeholders where API returned nothing
    unresolved = [r for r in rows if r["subscribers"] is None]
    if unresolved:
        print("\n[INFO] Artists with unresolved API stats (check channel id):")
        for r in unresolved:
            print(f"  - {r['artist_name']} -> {r['channel_id']}")


if __name__ == "__main__":
    main()
