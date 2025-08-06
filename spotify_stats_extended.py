# spotify_stats_extended.py

import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
from datetime import datetime

# Load environment variables
load_dotenv()
client_id = os.getenv("SPOTIPY_CLIENT_ID")
client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")

# Authenticate
auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
sp = spotipy.Spotify(auth_manager=auth_manager)

# Define artist names (you can change these)
artist_names = ["Bad Bunny", "Doja Cat", "Kendrick Lamar"]

artist_data = []
top_tracks_data = []

def get_artist_id(artist_name):
    result = sp.search(q=artist_name, type="artist", limit=1)
    return result['artists']['items'][0]['id'] if result['artists']['items'] else None

for name in artist_names:
    artist_id = get_artist_id(name)
    if not artist_id:
        print(f"❌ Couldn't find ID for {name}")
        continue

    # Artist metadata
    artist = sp.artist(artist_id)
    artist_data.append({
        "artist_name": artist['name'],
        "artist_id": artist['id'],
        "followers": artist['followers']['total'],
        "popularity": artist['popularity'],
        "genres": ", ".join(artist['genres']),
        "spotify_url": artist['external_urls']['spotify'],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    # Top tracks
    top_tracks = sp.artist_top_tracks(artist_id, country='US')
    for track in top_tracks['tracks']:
        top_tracks_data.append({
            "artist_name": artist['name'],
            "track_name": track['name'],
            "track_popularity": track['popularity'],
            "track_url": track['external_urls']['spotify'],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

# Save artist stats
artist_df = pd.DataFrame(artist_data)
artist_df.to_csv("spotify_stats.csv", mode='a', index=False, header=not os.path.exists("spotify_stats.csv"))

# Save top tracks stats
top_tracks_df = pd.DataFrame(top_tracks_data)
top_tracks_df.to_csv("spotify_top_tracks.csv", mode='a', index=False, header=not os.path.exists("spotify_top_tracks.csv"))

print("✅ Artist and top track stats saved.")