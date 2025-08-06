import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
from datetime import datetime

# Load credentials
load_dotenv()
client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")

# Set up Spotify API
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=client_id,
    client_secret=client_secret
))

# Test artist list
artist_ids = {
    "Bad Bunny": "4q3ewBCX7sLwd24euuV69X",
    "Doja Cat": "5cj0lLjcoR7YOSnhnX0Po5",
    "Kendrick Lamar": "2YZyLoL8N0Wb9xBt1NhZWg"
}

data = []

for name, artist_id in artist_ids.items():
    artist = sp.artist(artist_id)
    data.append({
        "artist_name": name,
        "followers": artist['followers']['total'],
        "popularity": artist['popularity'],
        "spotify_url": artist['external_urls']['spotify'],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

# Save to CSV
df = pd.DataFrame(data)
df.to_csv("spotify_stats.csv", mode='a', index=False, header=not os.path.exists("spotify_stats.csv"))
print("✅ Spotify stats saved to spotify_stats.csv")

from pprint import pprint

# For example:
artist = sp.artist("4q3ewBCX7sLwd24euuV69X")  # Bad Bunny
pprint(artist)
