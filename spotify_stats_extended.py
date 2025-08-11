# spotify_stats_extended.py
import os, csv, time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import pandas as pd
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import requests
from pathlib import Path

# ----------------- Config -----------------
ROLLING_DAYS = 90
ALERT_THRESHOLD_PCT = 0.2  # 0.2%
ARCHIVE_PATH = Path("archive/spotify_stats_archive.csv")
STATS_PATH = Path("spotify_stats.csv")
TOP_TRACKS_PATH = Path("spotify_top_tracks.csv")
RUNS_LOG = Path("runs.log")

# Optional webhook (Slack/Discord/etc.) – set as GitHub Secret or .env
load_dotenv()
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL")  # optional

client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
assert client_id and client_secret, "Missing SPOTIPY_CLIENT_ID/SECRET"

auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager)

# Your five artists (name → fixed ID)
ARTIST_IDS = {
    "Foo Fighters": "7jy3rLJdDQY21OgRLCZ9sD",
    "Weezer": "3jOstUTkEu2JkjvRdBA5Gu",
    "Kendrick Lamar": "2YZyLoL8N0Wb9xBt1NhZWg",
    "Bad Bunny": "4q3ewBCX7sLwd24euuV69X",
    "Taylor Swift": "06HL4z0CvFAxyc27GXpf02",
}

def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def ensure_dirs():
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)

def write_runs_log(line: str):
    with RUNS_LOG.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")

def send_webhook(text: str):
    if not ALERT_WEBHOOK_URL:
        return
    try:
        requests.post(ALERT_WEBHOOK_URL, json={"text": text}, timeout=8)
    except Exception:
        pass

def fetch_once():
    ts = now_utc_str()
    rows = []
    top_rows = []

    for name, artist_id in ARTIST_IDS.items():
        artist = sp.artist(artist_id)
        genres = ", ".join(artist.get("genres") or []) or None
        rows.append({
            "artist_name": artist["name"],
            "followers": artist["followers"]["total"],
            "popularity": artist["popularity"],
            "genres": genres,
            "spotify_url": artist["external_urls"]["spotify"],
            "timestamp": ts,
        })

        # top tracks US
        tt = sp.artist_top_tracks(artist_id, country="US")
        for t in tt.get("tracks", []):
            top_rows.append({
                "artist_name": artist["name"],
                "track_name": t.get("name"),
                "track_popularity": t.get("popularity"),
                "track_url": t.get("external_urls", {}).get("spotify"),
                "timestamp": ts,
            })

    return pd.DataFrame(rows), pd.DataFrame(top_rows)

def append_csv(df: pd.DataFrame, path: Path):
    header = not path.exists()
    df.to_csv(path, mode="a", index=False, header=header, quoting=csv.QUOTE_ALL)

def roll_and_archive():
    """Keep only last ROLLING_DAYS in STATS_PATH, move older to ARCHIVE_PATH."""
    if not STATS_PATH.exists():
        return
    df = pd.read_csv(STATS_PATH, quotechar='"', engine="python", on_bad_lines="skip")
    if df.empty or "timestamp" not in df.columns:
        return
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    cutoff = pd.Timestamp.now(tz=timezone.utc) - pd.Timedelta(days=ROLLING_DAYS)
    old = df[df["timestamp"] < cutoff]
    recent = df[df["timestamp"] >= cutoff]
    # append old to archive
    if not old.empty:
        ensure_dirs()
        header = not ARCHIVE_PATH.exists()
        old.to_csv(ARCHIVE_PATH, mode="a", index=False, header=header, quoting=csv.QUOTE_ALL)
    # overwrite with recent
    recent.to_csv(STATS_PATH, index=False, quoting=csv.QUOTE_ALL)

def compute_window_alerts(threshold_pct: float):
    """If any artist > threshold_pct change over last 24h, send webhook and return messages."""
    if not STATS_PATH.exists():
        return []
    df = pd.read_csv(STATS_PATH, quotechar='"', engine="python", on_bad_lines="skip")
    if df.empty:
        return []
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    cutoff = pd.Timestamp.now(tz=timezone.utc) - pd.Timedelta(hours=24)
    w = df[df["timestamp"] >= cutoff].copy()
    if w.empty:
        return []
    # earliest & latest per artist within window
    latest = w.sort_values("timestamp").groupby("artist_name").last(numeric_only=False)
    earliest = w.sort_values("timestamp").groupby("artist_name").first(numeric_only=False)
    msgs = []
    for artist in latest.index:
        end = latest.loc[artist, "followers"]
        start = earliest.loc[artist, "followers"]
        if pd.isna(start) or start == 0 or pd.isna(end):
            continue
        pct = (end - start) / start * 100
        if abs(pct) >= threshold_pct:
            msgs.append(f"{artist}: {pct:+.3f}% in last 24h (followers {int(start):,} → {int(end):,})")
    return msgs

def main():
    t0 = time.time()
    ok = True
    err = ""
    written = 0

    try:
        stats_df, top_df = fetch_once()
        if not stats_df.empty:
            append_csv(stats_df, STATS_PATH)
            written = len(stats_df)
        if not top_df.empty:
            append_csv(top_df, TOP_TRACKS_PATH)

        # hygiene: archive & roll last 90d
        roll_and_archive()

        # alerts
        alerts = compute_window_alerts(ALERT_THRESHOLD_PCT)
        if alerts:
            send_webhook("🚨 Spotify alerts:\n" + "\n".join(f"• {m}" for m in alerts))
    except Exception as e:
        ok = False
        err = str(e)
    finally:
        dur = time.time() - t0
        line = f"{now_utc_str()} | ok={int(ok)} | rows={written} | artists={len(ARTIST_IDS)} | dur={dur:.2f}s"
        if not ok:
            line += f" | err={err}"
        write_runs_log(line)

    print("✅ Artist and top track stats saved." if ok else f"❌ Run failed: {err}")

if __name__ == "__main__":
    main()
