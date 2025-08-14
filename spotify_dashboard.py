# spotify_dashboard.py
import os
from datetime import timedelta
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import os, subprocess, sys

colA, colB = st.columns([1, 9])
with colA:
    if st.button("⚡ Force fetch now"):
        script = "youtube_stats_extended.py"  # or "spotify_stats_extended.py" in that app
        try:
            out = subprocess.check_output([sys.executable, script], stderr=subprocess.STDOUT, text=True, timeout=240)
            st.success("Fetch ran. Reloading data…")
            st.caption(out)
            # clear cache & rerun
            for c in st.session_state.keys(): del st.session_state[c]
            st.rerun()
        except subprocess.CalledProcessError as e:
            st.error("Fetch error.")
            st.code(e.output)

st.set_page_config(
    page_title="Spotify Artist Stats",
    page_icon="🎧",
    layout="wide",
)

SPOTIFY_GREEN = "#1DB954"

st.markdown(
    f"""
    <style>
    .stMetric > div > div > div {{ color: {SPOTIFY_GREEN}; }}
    .smallgray {{ color:#8a8a8a;font-size:12px }}
    .badge {{ display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;
              background:#f1f5f9;border:1px solid #e5e7eb;margin-left:6px }}
    .badge.green {{ background:#ecfdf5;border-color:#a7f3d0;color:#047857 }}
    .badge.red   {{ background:#fef2f2;border-color:#fecaca;color:#b91c1c }}
    </style>
    """,
    unsafe_allow_html=True,
)

ARTIST_CSV = "spotify_stats.csv"
TRACK_CSV  = "spotify_top_tracks.csv"
ALERT_PCT  = 0.20  # 0.2%

def _ensure_utc(series: pd.Series) -> pd.Series:
    if series.dt.tz is None:
        return series.dt.tz_localize("UTC")
    return series.dt.tz_convert("UTC")

@st.cache_data(show_spinner=False)
def load_artists() -> pd.DataFrame:
    if not os.path.exists(ARTIST_CSV):
        return pd.DataFrame(
            columns=["artist_name","followers","popularity","genres","spotify_url","timestamp"]
        )
    df = pd.read_csv(
        ARTIST_CSV,
        parse_dates=["timestamp"],
        dtype={
            "artist_name":"string",
            "followers":"Int64",
            "popularity":"Int64",
            "genres":"string",
            "spotify_url":"string",
        },
        keep_default_na=False
    )
    # Normalize/rename if needed
    if "name" in df.columns and "artist_name" not in df.columns:
        df.rename(columns={"name":"artist_name"}, inplace=True)
    if "timestamp" in df.columns and not df.empty:
        df["timestamp"] = _ensure_utc(df["timestamp"])
    # Some early rows might not have genres; ensure column exists
    if "genres" not in df.columns:
        df["genres"] = ""
    return df

@st.cache_data(show_spinner=False)
def load_tracks() -> pd.DataFrame:
    if not os.path.exists(TRACK_CSV):
        return pd.DataFrame(
            columns=["artist_name","track_name","track_popularity","track_url","timestamp"]
        )
    df = pd.read_csv(
        TRACK_CSV,
        parse_dates=["timestamp"],
        dtype={
            "artist_name":"string",
            "track_name":"string",
            "track_popularity":"Int64",
            "track_url":"string",
        },
        keep_default_na=False
    )
    if "timestamp" in df.columns and not df.empty:
        df["timestamp"] = _ensure_utc(df["timestamp"])
    return df

def filter_window(df: pd.DataFrame, col: str, hours: int) -> pd.DataFrame:
    if df.empty: return df
    now_utc = pd.Timestamp.now(tz="UTC")
    start   = now_utc - timedelta(hours=hours)
    df[col] = _ensure_utc(df[col])
    return df[(df[col] >= start) & (df[col] <= now_utc)].copy()

def pct_change(first, last) -> float:
    try:
        if first in [0, None, np.nan] or pd.isna(first):
            return np.nan
        return (last - first) / float(first)
    except Exception:
        return np.nan

# --------- Data ----------
artists_df = load_artists()
tracks_df  = load_tracks()

st.title("Spotify Artist Stats Dashboard")
left, right = st.columns([2,2])

with left:
    if not artists_df.empty:
        default = sorted(artists_df["artist_name"].dropna().unique().tolist())
        options = default
    else:
        options, default = [], []
    sel = st.multiselect(
        "Choose artists to display",
        options=options,
        default=default[:5],
    )

with right:
    win = st.slider("Time window (hours)", 6, 168, 48, 1)

# Header info
st.caption(
    f"Last fetch: "
    f"{(artists_df['timestamp'].max().strftime('%Y-%m-%d %H:%M:%S UTC') if not artists_df.empty else '—')} "
    f"| <span class='smallgray'>artist rows={len(artists_df):,} | tracks rows={len(tracks_df):,}</span>",
    help=None,
)

if st.button("🔄 Reload data", type="secondary"):
    load_artists.clear()
    load_tracks.clear()
    try:
        st.rerun()
    except Exception:
        pass

if artists_df.empty:
    st.info("No artist snapshots yet — run your Spotify fetcher.")
    st.stop()

if not sel:
    st.warning("Select at least one artist.")
    st.stop()

# Filter window
w = filter_window(artists_df[artists_df["artist_name"].isin(sel)], "timestamp", win)
wt = filter_window(tracks_df[tracks_df["artist_name"].isin(sel)], "timestamp", win)

if w.empty:
    st.warning("No artist snapshots found in this time window.")
    st.stop()

# Latest snapshot per artist
latest = w.sort_values("timestamp").groupby("artist_name").tail(1)

# KPIs
m1, m2, m3 = st.columns(3)
m1.metric("Total Followers", f"{int(latest['followers'].fillna(0).sum()):,}")
m2.metric("Avg Popularity",  f"{latest['popularity'].astype('float').mean():.1f}")
m3.metric("Artists in View", f"{latest['artist_name'].nunique():,}")

# Alerts
sorted_w = w.sort_values("timestamp")
start_df = sorted_w.groupby("artist_name").head(1)
end_df   = sorted_w.groupby("artist_name").tail(1)
chg = start_df[["artist_name","followers"]].merge(
    end_df[["artist_name","followers"]],
    on="artist_name", suffixes=("_start","_end")
)
chg["pct"] = chg.apply(lambda r: pct_change(r["followers_start"], r["followers_end"]), axis=1)
hits = chg[(~chg["pct"].isna()) & (chg["pct"].abs() >= ALERT_PCT/100.0)]
if not hits.empty:
    msg = " • ".join(f"{r.artist_name}: {r.pct*100:+.3f}%" for r in hits.itertuples(index=False))
    st.markdown(f"<div class='badge red'>Alert: Δ followers > {ALERT_PCT:.1f}% → {msg}</div>", unsafe_allow_html=True)

# Tabs
t1, t2, t3 = st.tabs(["📊 Current Stats", "📈 Trends", "🎵 Top Tracks"])

with t1:
    st.subheader("Current Stats Summary")
    show = latest[["artist_name","followers","popularity","genres","spotify_url","timestamp"]].sort_values("artist_name")
    st.dataframe(show, use_container_width=True)

with t2:
    st.subheader("Followers Over Time")
    figf = px.line(
        w.sort_values("timestamp"),
        x="timestamp", y="followers", color="artist_name",
        labels={"timestamp":"timestamp","followers":"followers","artist_name":"artist"},
    )
    st.plotly_chart(figf, use_container_width=True)

    st.subheader("Popularity Over Time")
    figp = px.line(
        w.sort_values("timestamp"),
        x="timestamp", y="popularity", color="artist_name",
        labels={"timestamp":"timestamp","popularity":"popularity","artist_name":"artist"},
    )
    st.plotly_chart(figp, use_container_width=True)

with t3:
    st.subheader("Top Tracks (within snapshot window)")
    if wt.empty:
        st.caption("No top track snapshots in this window.")
    else:
        # show the most recent record per (artist, track) for clarity
        latest_tracks = wt.sort_values("timestamp").groupby(["artist_name","track_name"]).tail(1)
        latest_tracks = latest_tracks.sort_values(["artist_name","track_popularity"], ascending=[True, False])
        showt = latest_tracks[["artist_name","track_name","track_popularity","track_url","timestamp"]]
        st.dataframe(showt, use_container_width=True)
