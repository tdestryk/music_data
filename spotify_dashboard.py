# spotify_dashboard.py
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

# -----------------------------
# Theme / page config
# -----------------------------
st.set_page_config(
    page_title="Spotify Artist Stats Dashboard",
    layout="wide",
)

SPOTIFY_CSV = "spotify_stats.csv"
TOPTRACKS_CSV = "spotify_top_tracks.csv"

# If you want to force a branch for raw fallback:
DEFAULT_BRANCH = os.getenv("GITHUB_DEFAULT_BRANCH", "main")
# You can hardcode your repo if needed:
DEFAULT_REPO = os.getenv("GITHUB_REPOSITORY", "")  # "tdestrk/music_data" if you want to hardcode


# -----------------------------
# Utils
# -----------------------------
def _raw_url(path: str) -> Optional[str]:
    """
    Build a raw.githubusercontent URL if we know the repo/owner.
    """
    repo = DEFAULT_REPO or os.getenv("CODESPACE_NAME", "")
    # If repo is empty, return None. In Codespaces GITHUB_REPOSITORY is usually set;
    # If not, you can hardcode: return "https://raw.githubusercontent.com/<owner>/<repo>/<branch>/" + path
    if not DEFAULT_REPO:
        return None
    owner_repo = DEFAULT_REPO  # e.g., "tdestryk/music_data"
    return f"https://raw.githubusercontent.com/{owner_repo}/{DEFAULT_BRANCH}/{path}"


@st.cache_data(show_spinner=False, ttl=60)
def load_csv(path: str) -> pd.DataFrame:
    """
    Try local path; if missing, try raw GitHub URL; else return empty DF.
    """
    if os.path.exists(path):
        return pd.read_csv(path)
    url = _raw_url(path)
    if url:
        try:
            return pd.read_csv(url)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def parse_ts(series: pd.Series, col: str = "timestamp") -> pd.Series:
    """
    Parse timestamps to tz-aware UTC.
    Works whether input strings are naive or tz-aware.
    """
    s = pd.to_datetime(series, utc=True, errors="coerce")
    return s


def filter_window(df: pd.DataFrame, hours: int, ts_col: str = "timestamp") -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df[ts_col] = parse_ts(df[ts_col])
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    mask = (df[ts_col] >= start) & (df[ts_col] <= end)
    return df.loc[mask]


def latest_per_artist(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    idx = (
        df.sort_values("timestamp")
          .groupby("artist_name", as_index=False)
          .tail(1)
          .set_index("artist_name")
    )
    return idx.reset_index()


# -----------------------------
# Load data
# -----------------------------
artists_raw = load_csv(SPOTIFY_CSV)
tracks_raw = load_csv(TOPTRACKS_CSV)

# Guard columns (older rows may have different headers)
expected_artist_cols = {"artist_name", "followers", "popularity", "spotify_url", "genres", "timestamp"}
if not artists_raw.empty:
    missing = expected_artist_cols - set(artists_raw.columns)
    # Fill any missing expected columns so downstream code doesn't crash
    for m in missing:
        artists_raw[m] = pd.NA

# -----------------------------
# Header
# -----------------------------
with st.container():
    st.markdown("## 🎧 Spotify Artist Stats Dashboard")
    # stats line
    artist_rows = len(artists_raw)
    track_rows = len(tracks_raw)
    last_ts = (
        parse_ts(artists_raw["timestamp"]).max().strftime("%Y-%m-%d %H:%M:%S UTC")
        if not artists_raw.empty else "—"
    )
    st.caption(f"Last fetch: **{last_ts}** | artist rows={artist_rows} | tracks rows={track_rows}")

# Controls
default_artists = ["Bad Bunny", "Foo Fighters", "Kendrick Lamar", "Taylor Swift", "Weezer"]
all_artists = sorted(artists_raw["artist_name"].dropna().unique().tolist()) if not artists_raw.empty else default_artists

col_left, col_right = st.columns([3, 1])
with col_left:
    selected = st.multiselect(
        "Choose artists to display",
        options=all_artists,
        default=[a for a in default_artists if a in all_artists] or all_artists[:5],
    )
with col_right:
    hours = st.slider("Time window (hours)", min_value=6, max_value=336, value=24, step=6)

st.button("🔁 Reload data", on_click=lambda: st.cache_data.clear())

# Windowed frames
artists = filter_window(artists_raw, hours)
tracks = filter_window(tracks_raw, hours, ts_col="timestamp")

if not selected:
    st.info("No artists selected.")
    st.stop()

w = artists[artists["artist_name"].isin(selected)]

if w.empty:
    st.warning("No artist snapshots found in this time window.")
    st.stop()

# -----------------------------
# KPIs
# -----------------------------
k1, k2, k3 = st.columns(3)
latest = latest_per_artist(w)

with k1:
    st.metric("Total Followers", f"{int(latest['followers'].fillna(0).sum()):,}")
with k2:
    st.metric("Avg Popularity", f"{latest['popularity'].fillna(0).mean():.1f}")
with k3:
    st.metric("Artists in View", f"{latest['artist_name'].nunique():,}")

# -----------------------------
# Tabs
# -----------------------------
tab1, tab2, tab3 = st.tabs(["📋 Current Snapshot", "📈 Followers Over Time", "🎵 Top Tracks"])

# --- Snapshot
with tab1:
    st.subheader("Current Stats Summary")
    st.dataframe(
        latest[["artist_name", "followers", "popularity", "genres", "spotify_url"]].set_index("artist_name"),
        use_container_width=True
    )

# --- Followers Over Time
with tab2:
    st.subheader("Followers Over Time")
    w2 = w.sort_values("timestamp")
    fig = px.line(
        w2,
        x="timestamp",
        y="followers",
        color="artist_name",
        markers=True,
        labels={"timestamp": "Date", "followers": "Followers"},
    )
    fig.update_layout(legend_title_text="Artist")
    st.plotly_chart(fig, use_container_width=True)

# --- Top Tracks (window)
with tab3:
    st.subheader("Top Tracks (in window)")
    if tracks.empty:
        st.caption("No track snapshots in this window.")
    else:
        tsel = tracks[tracks["artist_name"].isin(selected)].copy()
        if "track_popularity" in tsel.columns:
            tsel = tsel.sort_values(["artist_name", "track_popularity"], ascending=[True, False])
            st.dataframe(
                tsel[["artist_name", "track_name", "track_popularity", "track_url", "timestamp"]],
                use_container_width=True,
                height=500
            )
        else:
            st.caption("Your top-tracks CSV doesn't have 'track_popularity'; showing raw rows.")
            st.dataframe(tsel, use_container_width=True)
