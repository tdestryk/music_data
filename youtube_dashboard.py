# youtube_dashboard.py
# YouTube stats with links, thumbnails, Δ toggle, auto-zoom, 7d change, and polished charts.

import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from googleapiclient.discovery import build
import altair as alt

st.set_page_config(page_title="YouTube Artist Stats", page_icon="📹", layout="wide")

# ---------- Secrets ----------
load_dotenv()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    st.error("Missing YOUTUBE_API_KEY in .env or host secrets.")
    st.stop()

CSV_PATH  = "youtube_stats.csv"
LINKS_CSV = "artist_links.csv"   # needs: artist_name,youtube_channel_id and optional links/color_hex

# ---------- Helpers ----------
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
        return pd.DataFrame(columns=["timestamp","artist_name","channel_id","subscribers","views","thumb_url"])
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
          .drop_duplicates(subset=["channel_id","ts_min"], keep="last"))
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
    for need in ["artist_name","youtube_channel_id","youtube_url","spotify_url","facebook_url",
                 "instagram_url","tiktok_url","twitter_url","website_url","color_hex"]:
        if need not in df.columns: df[need] = ""
    return df

# ---------- API ----------
@st.cache_resource(show_spinner=False)
def get_youtube():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY, cache_discovery=False)

yt = get_youtube()

def fetch_channel(cid: str) -> dict:
    r = yt.channels().list(part="statistics,snippet", id=cid).execute()
    items = r.get("items", [])
    if not items: return {}
    it = items[0]
    stats = it["statistics"]
    title = it["snippet"]["title"]
    thumbs = it["snippet"].get("thumbnails", {})
    # prefer high/medium/default
    thumb = thumbs.get("high", {}).get("url") or thumbs.get("medium", {}).get("url") or thumbs.get("default", {}).get("url") or ""
    return {
        "timestamp": now_utc(),
        "artist_name": title,         # YouTube title; we’ll map when displaying
        "channel_id": cid,
        "subscribers": int(stats.get("subscriberCount", 0)),
        "views": int(stats.get("viewCount", 0)),
        "thumb_url": thumb,
    }

# ---------- UI ----------
st.title("📹 YouTube Dashboard")

with st.sidebar:
    st.markdown("### Data Tools")
    if st.button("🛠 Fix timestamps (normalize)"):
        normalize_csv(CSV_PATH); st.success("CSV normalized to UTC ISO.")
    st.caption("All times in UTC")

default_artists = ["Bad Bunny","Kendrick Lamar","Foo Fighters","Taylor Swift","Weezer"]
artists = st.multiselect("Select channels (by artist)", default_artists, default=default_artists)

c1, c2, c3 = st.columns(3)
with c1: hours = st.slider("Time window (hours)", 1, 168, 72)
with c2: show_delta = st.toggle("Show Δ change", value=False)
with c3: auto_zoom = st.toggle("Auto-zoom y-axis", value=True)

links_df = load_links()
chan_map = {}
if not links_df.empty and "youtube_channel_id" in links_df.columns:
    selected = links_df[links_df["artist_name"].isin(artists)]
    chan_map = dict(zip(selected["artist_name"], selected["youtube_channel_id"]))

missing = [a for a in artists if a not in chan_map]
if missing:
    st.warning(f"Missing channel IDs for: {', '.join(missing)}. Add them to {LINKS_CSV}")

if st.button("🔄 Reload data") and chan_map:
    with st.spinner("Fetching latest YouTube stats…"):
        for artist, cid in chan_map.items():
            row = fetch_channel(cid)
            if not row: 
                st.warning(f"Couldn’t fetch stats for {artist} ({cid})")
                continue
            # store with the friendly artist name from CSV (not YouTube title)
            row["artist_name"] = artist
            upsert_snapshot(CSV_PATH, row)
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
view["subs_delta"]  = view.groupby("artist_name")["subscribers"].diff()
view["views_delta"] = view.groupby("artist_name")["views"].diff()

# 7-day change
cut = now_utc() - pd.Timedelta(days=7)
seven = hist[hist["artist_name"].isin(artists)].copy()
seven = seven[to_utc(seven["timestamp"]) >= cut]
agg = (seven.sort_values("timestamp")
             .groupby("artist_name")
             .agg(last_subs=("subscribers","last"),
                  first_subs=("subscribers","first"),
                  last_views=("views","last"),
                  first_views=("views","first"))
             .reset_index())
agg["subs_Δ7d"] = agg["last_subs"] - agg["first_subs"]
agg["views_Δ7d"] = agg["last_views"] - agg["first_views"]

st.subheader("Δ in Last 7 Days (YouTube)")
st.dataframe(agg[["artist_name","last_subs","subs_Δ7d","last_views","views_Δ7d"]],
             use_container_width=True)

# merge links & latest
latest = (view.sort_values("timestamp")
              .groupby("artist_name", as_index=False)
              .tail(1)
              .sort_values("artist_name"))
if not links_df.empty:
    keep = ["artist_name","youtube_url","spotify_url","facebook_url","instagram_url",
            "tiktok_url","twitter_url","website_url"]
    for k in keep:
        if k not in links_df.columns: links_df[k] = ""
    latest = latest.merge(links_df[["artist_name"]+keep], on="artist_name", how="left")

st.subheader("Latest Snapshot (with links)")
st.data_editor(
    latest[["thumb_url","artist_name","subscribers","subs_delta","views","views_delta","timestamp",
            "youtube_url","facebook_url","instagram_url","tiktok_url","twitter_url","website_url","spotify_url"]],
    hide_index=True,
    use_container_width=True,
    column_config={
        "thumb_url":     st.column_config.ImageColumn("Thumb", help="Channel thumbnail"),
        "youtube_url":   st.column_config.LinkColumn("YouTube"),
        "facebook_url":  st.column_config.LinkColumn("Facebook"),
        "instagram_url": st.column_config.LinkColumn("Instagram"),
        "tiktok_url":    st.column_config.LinkColumn("TikTok"),
        "twitter_url":   st.column_config.LinkColumn("X/Twitter"),
        "website_url":   st.column_config.LinkColumn("Website"),
        "spotify_url":   st.column_config.LinkColumn("Spotify"),
    }
)

# ---------- Color map ----------
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

# ---------- Pretty charts ----------
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

# subscribers
y_field = "subs_delta" if show_delta else "subscribers"
y_title = "Δ Subscribers" if show_delta else "Subscribers"
subs_domain = None
if auto_zoom and not show_delta:
    v = view[y_field].dropna()
    if not v.empty:
        lo, hi = float(v.min()), float(v.max())
        if lo == hi: lo, hi = lo*0.99, hi*1.01
        pad = max((hi-lo)*0.05, 1.0); subs_domain = [lo-pad, hi+pad]

st.subheader("Subscribers Over Time")
st.altair_chart(pretty_series(view, y_field, y_title, subs_domain), use_container_width=True)

# views
v_field = "views_delta" if show_delta else "views"
v_title = "Δ Views" if show_delta else "Views"
st.subheader("Views Over Time")
st.altair_chart(pretty_series(view, v_field, v_title), use_container_width=True)

st.caption("All timestamps are UTC. Toggle Δ to see change; Auto-zoom highlights subtle movements.")
