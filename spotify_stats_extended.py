# spotify_stats_extended.py
import os
import csv
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# --- Auth ---
load_dotenv()
client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=client_id, client_secret=client_secret
))

# --- Artists you track ---
ARTIST_IDS = {
    "Foo Fighters": "7jy3rLJdDQY21OgRLCZ9sD",
    "Weezer": "3jOstUTkEu2JkjvRdBA5Gu",
    "Kendrick Lamar": "2YZyLoL8N0Wb9xBt1NhZWg",
    "Bad Bunny": "4q3ewBCX7sLwd24euuV69X",
    "Taylor Swift": "06HL4z0CvFAxyc27GXpf02",
}

# --- Pull data from Spotify ---
artist_rows = []
top_track_rows = []

now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

for name, artist_id in ARTIST_IDS.items():
    try:
        a = sp.artist(artist_id)
        artist_rows.append({
            "artist_name": a["name"],
            "followers": a["followers"]["total"],
            "popularity": a["popularity"],
            # join with commas; we will quote CSV fields so commas are safe
            "genres": ", ".join(a.get("genres", [])) if a.get("genres") else None,
            "spotify_url": a["external_urls"]["spotify"],
            "timestamp": now_str,
        })

        # (Optional) keep a rolling top-tracks table for future widgets
        tt = sp.artist_top_tracks(artist_id, country="US")
        for t in tt.get("tracks", []):
            top_track_rows.append({
                "artist_name": a["name"],
                "track_name": t["name"],
                "track_popularity": t["popularity"],
                "track_url": t["external_urls"]["spotify"],
                "timestamp": now_str,
            })

    except Exception as e:
        print(f"❌ Error processing {name}: {e}")

# --- Save CSVs (append safely, quote all fields) ---
def append_csv(df: pd.DataFrame, path: str):
    df.to_csv(
        path,
        mode="a",
        index=False,
        header=not os.path.exists(path),
        quoting=csv.QUOTE_ALL
    )

if artist_rows:
    append_csv(pd.DataFrame(artist_rows), "spotify_stats.csv")

if top_track_rows:
    append_csv(pd.DataFrame(top_track_rows), "spotify_top_tracks.csv")

print("✅ Artist and top track stats saved.")
# 1) Make the folders (the -p creates parents if missing)
mkdir -p .github/workflows

# 2) Create and open the workflow file in your terminal editor
nano .github/workflows/fetch_spotify.yml
