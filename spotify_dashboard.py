# spotify_dashboard.py
# Spotify stats with links, images, Δ toggle, auto-zoom, 7d change, and polished charts.

import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
import altair as alt

st.set_page_config(page_title="Spotify Artist Stats", page_icon="🎧", layout="wide")

# ---------- Secrets ----------
load_dotenv()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    st.error("Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in .env or host secrets.")
    st.stop()

CSV_PATH   = "spotify_stats.csv"
LINKS_CSV  = "artist_links.csv"   # csv with artist_name + links (and optional color_hex)

# ---------- Time & CSV helpers ----------
def now_utc() -> pd.Timestamp: return pd.Timestamp.now(tz="UTC")
def to_utc(x) -> pd.Series: return pd.to_datetime(x, utc=True, errors="coerce")

def normalize_csv(p: str):
    if not os.path.exists(p): return
    df = pd.read_csv(p)
    if "timestamp" in df.columns:
        df["timestamp"] = to_utc(df["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        df.to_csv(p, index=False)

def load_history(p: str) -> pd.DataFrame:
    if not os.path.exists(p):
        return pd.DataFrame(columns=["timestamp","artist_name","artist_id","followers","popularity","genres","avg_top_track_pop","image_url"])
    df = pd.read_csv(p)
    if "timestamp" in df.columns: df["timestamp"] = to_utc(df["timestamp"])
    return df

def save_history(p: str, df: pd.DataFrame):
    out = df.copy()
    out["timestamp"] = to_utc(out["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(p, index=False)

def upsert_snapshot(p: str, row: dict):
    hist = load_history(p)
    new  = pd.DataFrame([row])
    c = pd.concat([hist, new], ignore_index=True)
    c["timestamp"] = to_utc(c["timestamp"])
    c["ts_min"] = c["timestamp"].dt.floor("T")
    c = (c.sort_values("timestamp")
          .drop_duplicates(subset=["artist_id","ts_min"], keep="last"))
    c.drop(columns=["ts_min"], inplace=True)
    save_history(p, c)

def filter_window(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    if df.empty: return df
    ts = to_utc(df["timestamp"])
    df = df.loc[ts.notna()].copy(); ts = ts.loc[ts.notna()]
    end = now_utc(); start = end - pd.Timedelta(hours=hours)
    return df.loc[(ts >= start) & (ts <= end)].copy()

def load_links() -> pd.DataFrame:
    if not os.path.exists(LINKS_CSV): return pd.DataFrame()
    df = pd.read_csv(LINKS_CSV)
    # normalize expected columns
    for need in ["artist_name","spotify_url","youtube_url","facebook_url","instagram_url",
                 "tiktok_url","twitter_url","website_url","color_hex"]:
        if need not in df.columns: df[need] = ""
    return df

# ---------- Spotify API ----------
@st.cache_resource(show_spinner=False)
def get_spotify() -> Spotify:
    auth = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
    return Spotify(auth_manager=auth)

sp = get_spotify()

def search_artist_id(name: str) -> str | None:
    res = sp.search(q=name, type="artist", limit=1)
    items = res.get("artists", {}).get("items", [])
    return items[0]["id"] if items else None

def fetch_snapshot(artist_id: str) -> dict:
    a = sp.artist(artist_id)
    followers = a.get("followers", {}).get("total")
    pop = a.get("popularity")
    name = a.get("name", "")
    genres = ", ".join(a.get("genres", []))
    img = ""
    imgs = a.get("images") or []
    if imgs: img = imgs[0].get("url", "")
    tt = sp.artist_top_tracks(artist_id, country="US").get("tracks", [])
    pops = [t.get("popularity", 0) for t in tt]
    avg_top = round(sum(pops)/len(pops), 2) if pops else None
    return {
        "timestamp": now_utc(),
        "artist_name": name,
        "artist_id": artist_id,
        "followers": followers,
        "popularity": pop,
        "genres": genres,
        "avg_top_track_pop": avg_top,
        "image_url": img,
    }

# ---------- UI ----------
st.title("🎧 Spotify Dashboard")

with st.sidebar:
    st.markdown("### Data Tools")
    if st.button("🛠 Fix timestamps (normalize)"):
        normalize_csv(CSV_PATH); st.success("CSV timestamps normalized to UTC ISO.")
    st.caption("All times in UTC")

default_artists = ["Bad Bunny","Foo Fighters","Kendrick Lamar","Taylor Swift","Weezer"]
artists = st.multiselect("Select artists", default_artists, default=default_artists)

c1, c2, c3 = st.columns(3)
with c1: hours = st.slider("Time window (hours)", 1, 168, 72)
with c2: show_delta = st.toggle("Show Δ change", value=False)
with c3: auto_zoom = st.toggle("Auto-zoom y-axis", value=True)

if st.button("🔄 Reload data") and artists:
    with st.spinner("Fetching latest Spotify stats…"):
        for name in artists:
            aid = search_artist_id(name)
            if not aid:
                st.warning(f"Could not find artist id for {name}")
                continue
            upsert_snapshot(CSV_PATH, fetch_snapshot(aid))
    st.success("Updated snapshots!"); st.rerun()

# ---------- Data prep ----------
normalize_csv(CSV_PATH)
hist = load_history(CSV_PATH)
view = hist[hist["artist_name"].isin(artists)].copy()
view = filter_window(view, hours)
if view.empty:
    st.info("No rows in window. Reload data or widen the window.")
    st.stop()

# deltas
view = view.sort_values(["artist_name","timestamp"])
view["followers_delta"]  = view.groupby("artist_name")["followers"].diff()
view["popularity_delta"] = view.groupby("artist_name")["popularity"].diff()

# 7-day change
cut = now_utc() - pd.Timedelta(days=7)
seven = hist[hist["artist_name"].isin(artists)].copy()
seven = seven[to_utc(seven["timestamp"]) >= cut]
agg = (seven.sort_values("timestamp")
             .groupby("artist_name")
             .agg(last_followers=("followers","last"),
                  first_followers=("followers","first"),
                  last_pop=("popularity","last"),
                  first_pop=("popularity","first"))
             .reset_index())
agg["followers_Δ7d"] = agg["last_followers"] - agg["first_followers"]
agg["popularity_Δ7d"] = agg["last_pop"] - agg["first_pop"]

st.subheader("Δ in Last 7 Days (Spotify)")
st.dataframe(agg[["artist_name","last_followers","followers_Δ7d","last_pop","popularity_Δ7d"]],
             use_container_width=True)

# merge links & latest
links_df = load_links()
latest = (view.sort_values("timestamp")
              .groupby("artist_name", as_index=False)
              .tail(1)
              .sort_values("artist_name"))
if not links_df.empty:
    latest = latest.merge(links_df, on="artist_name", how="left")

st.subheader("Latest Snapshot (with links)")
st.data_editor(
    latest[["image_url","artist_name","followers","followers_delta","popularity","popularity_delta",
            "avg_top_track_pop","genres","timestamp","spotify_url","youtube_url","facebook_url",
            "instagram_url","tiktok_url","twitter_url","website_url"]],
    hide_index=True,
    use_container_width=True,
    column_config={
        "image_url":   st.column_config.ImageColumn("Image", help="Artist image"),
        "spotify_url": st.column_config.LinkColumn("Spotify"),
        "youtube_url": st.column_config.LinkColumn("YouTube"),
        "facebook_url":st.column_config.LinkColumn("Facebook"),
        "instagram_url":st.column_config.LinkColumn("Instagram"),
        "tiktok_url":  st.column_config.LinkColumn("TikTok"),
        "twitter_url": st.column_config.LinkColumn("X/Twitter"),
        "website_url": st.column_config.LinkColumn("Website"),
    }
)

# ---------- Color map ----------
# If links CSV has color_hex per artist, use it; else fall back to Tableau scheme
artist_colors = {}
if not links_df.empty and "color_hex" in links_df.columns:
    for _, r in links_df.dropna(subset=["artist_name"]).iterrows():
        if isinstance(r.get("color_hex"), str) and r["color_hex"].strip():
            artist_colors[r["artist_name"]] = r["color_hex"].strip()

def alt_color():
    return alt.Scale(
        domain=list(artist_colors.keys()) if artist_colors else alt.Undefined,
        range=list(artist_colors.values()) if artist_colors else alt.Undefined,
        scheme=None if artist_colors else "tableau10",
    )

# ---------- Pretty charts (area + smoothed line + big points) ----------
def pretty_series(df: pd.DataFrame, yfield: str, title: str, domain=None):
    base = alt.Chart(df).encode(
        x=alt.X("timestamp:T", title="Time (UTC)"),
        color=alt.Color("artist_name:N", scale=alt_color(), legend=alt.Legend(title=None)),
        tooltip=["artist_name", yfield, "timestamp"]
    )
    area = base.mark_area(opacity=0.15, interpolate="monotone").encode(
        y=alt.Y(f"{yfield}:Q", title=title,
                scale=(alt.Scale(domain=domain) if domain else alt.Undefined))
    )
    line = base.mark_line(interpolate="monotone", strokeWidth=2.5).encode(
        y=alt.Y(f"{yfield}:Q", title=title,
                scale=(alt.Scale(domain=domain) if domain else alt.Undefined))
    )
    pts = base.mark_circle(size=70).encode(y=f"{yfield}:Q")
    return (area + line + pts).properties(height=320)

# followers
y_field = "followers_delta" if show_delta else "followers"
y_title = "Δ Followers" if show_delta else "Followers"
followers_domain = None
if auto_zoom and not show_delta:
    v = view[y_field].dropna()
    if not v.empty:
        lo, hi = float(v.min()), float(v.max())
        if lo == hi: lo, hi = lo*0.99, hi*1.01
        pad = max((hi-lo)*0.05, 1.0); followers_domain = [lo-pad, hi+pad]

st.subheader("Followers Over Time")
st.altair_chart(pretty_series(view, y_field, y_title, followers_domain), use_container_width=True)

# popularity
p_field = "popularity_delta" if show_delta else "popularity"
p_title = "Δ Popularity" if show_delta else "Popularity (0–100)"
st.subheader("Popularity Over Time")
st.altair_chart(pretty_series(view, p_field, p_title), use_container_width=True)

st.caption("All timestamps are stored/displayed in UTC. Toggle Δ to see change; Auto-zoom tightens the y-axis to show small moves.")
