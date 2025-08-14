# spotify_dashboard.py
import os
import pandas as pd
import numpy as np
import streamlit as st

# ---------- Page setup ----------
st.set_page_config(page_title="Spotify Artist Stats Dashboard", layout="wide", page_icon="🎧")

SPOTIFY_CSV = os.getenv("SPOTIFY_CSV", "spotify_stats.csv")
TOP_TRACKS_CSV = os.getenv("TOP_TRACKS_CSV", "spotify_top_tracks.csv")

# ---------- Helpers ----------

def read_csv_safe(path: str) -> pd.DataFrame:
    """
    Read a CSV resiliently:
      - tolerate extra columns/commas
      - don't crash on bad rows
      - auto-parse timestamp column when present
    """
    if not os.path.exists(path):
        return pd.DataFrame()

    try:
        df = pd.read_csv(
            path,
            engine="python",                # more forgiving parser
            encoding="utf-8",
            on_bad_lines="skip" if "on_bad_lines" in pd.read_csv.__code__.co_varnames else None,
        )
    except TypeError:
        # in case this pandas doesn't support on_bad_lines kw
        df = pd.read_csv(path, engine="python", encoding="utf-8")

    # normalize timestamp if present
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp"])

    return df


def filter_window(df: pd.DataFrame, hours: int, ts_col: str = "timestamp") -> pd.DataFrame:
    """Return rows within the last N hours, using UTC."""
    if df.empty or ts_col not in df.columns:
        return df

    end = pd.Timestamp.utcnow().tz_localize("UTC")
    start = end - pd.Timedelta(hours=hours)

    # ensure tz-aware
    if df[ts_col].dt.tz is None:
        df[ts_col] = df[ts_col].dt.tz_localize("UTC")

    return df[(df[ts_col] >= start) & (df[ts_col] <= end)].copy()


@st.cache_data(show_spinner=False)
def load_data():
    artists = read_csv_safe(SPOTIFY_CSV)
    tracks = read_csv_safe(TOP_TRACKS_CSV)

    # normalize column names we rely on
    want_artist_cols = ["artist_name", "followers", "popularity", "spotify_url", "timestamp"]
    for col in want_artist_cols:
        if col not in artists.columns:
            artists[col] = np.nan

    # force dtypes
    for col in ["followers", "popularity"]:
        artists[col] = pd.to_numeric(artists[col], errors="coerce")

    # genres may or may not be present
    if "genres" not in artists.columns:
        artists["genres"] = np.nan

    # tracks normalization
    want_track_cols = ["artist_name", "track_name", "track_popularity", "track_url", "timestamp"]
    for col in want_track_cols:
        if col not in tracks.columns:
            tracks[col] = np.nan
    tracks["track_popularity"] = pd.to_numeric(tracks["track_popularity"], errors="coerce")

    return artists, tracks


def latest_snapshot(artists_df: pd.DataFrame) -> pd.DataFrame:
    """Last row per artist by timestamp."""
    if artists_df.empty:
        return artists_df
    return (
        artists_df.sort_values("timestamp")
                  .groupby("artist_name", as_index=False)
                  .tail(1)
                  .reset_index(drop=True)
    )


def delta_by_artist(window_df: pd.DataFrame) -> pd.DataFrame:
    """Compute follower delta per artist inside the window."""
    if window_df.empty:
        return window_df

    g = window_df.sort_values("timestamp").groupby("artist_name", as_index=False)
    agg = g.agg(first_followers=("followers", "first"),
                last_followers=("followers", "last"),
                first_pop=("popularity", "first"),
                last_pop=("popularity", "last"))
    agg["followers_delta"] = agg["last_followers"] - agg["first_followers"]
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["followers_pct"] = np.where(
            agg["first_followers"] > 0,
            (agg["followers_delta"] / agg["first_followers"]) * 100.0,
            np.nan
        )
    agg["pop_delta"] = agg["last_pop"] - agg["first_pop"]
    return agg


# ---------- UI Header ----------

st.title("🎧 Spotify Artist Stats Dashboard")

colh1, colh2 = st.columns([1, 1])
with colh1:
    if st.button("🔄 Reload data", use_container_width=False):
        st.cache_data.clear()
        st.rerun()

artists_df, tracks_df = load_data()

# Artist multi-select
all_artists = sorted(artists_df["artist_name"].dropna().unique().tolist())
default_sel = all_artists[:5]
sel = st.multiselect("Choose artists to display", all_artists, default=default_sel)

# Time window
win = st.slider("Time window (hours)", min_value=1, max_value=168, value=72)

# Apply filters
artists_sel = artists_df[artists_df["artist_name"].isin(sel)] if sel else artists_df
artists_win = filter_window(artists_sel, win, "timestamp")

# Compute snapshots safely (avoid NameError)
latest = latest_snapshot(artists_sel)

# Summary metrics
m1, m2, m3 = st.columns(3)
if latest.empty:
    m1.metric("Total Followers", "0")
    m2.metric("Avg Popularity", "0.0")
    m3.metric("Artists in View", "0")
else:
    m1.metric("Total Followers", f"{int(latest['followers'].fillna(0).sum()):,}")
    m2.metric("Avg Popularity", f"{latest['popularity'].dropna().mean():.1f}")
    m3.metric("Artists in View", f"{latest['artist_name'].nunique()}")

# ---------- Tabs ----------
tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 Current Stats Summary", "📈 Followers Over Time", "🆚 Compare Artists", "🎵 Top Tracks"]
)

with tab1:
    st.subheader("Current Stats Summary")
    if latest.empty:
        st.info("No artist snapshots found in this time window.")
    else:
        cols = ["artist_name", "followers", "popularity", "genres", "spotify_url", "timestamp"]
        show = [c for c in cols if c in latest.columns]
        st.dataframe(latest[show].sort_values("followers", ascending=False), use_container_width=True)

with tab2:
    st.subheader("Followers Over Time")
    if artists_win.empty:
        st.warning("No data points in this time window.")
    else:
        import plotly.express as px
        fig = px.line(
            artists_win.sort_values("timestamp"),
            x="timestamp",
            y="followers",
            color="artist_name",
            labels={"timestamp": "Time (UTC)", "followers": "Spotify Followers", "artist_name": "Artist"},
        )
        st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Compare Artists (Δ in window)")
    delta = delta_by_artist(artists_win)
    if delta.empty:
        st.info("No change data in this window yet.")
    else:
        import plotly.express as px
        fig = px.bar(
            delta.sort_values("followers_delta", ascending=False),
            x="artist_name",
            y="followers_delta",
            color="followers_pct",
            color_continuous_scale="RdYlGn",
            labels={"artist_name": "Artist", "followers_delta": "Δ Followers", "followers_pct": "% change"},
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(delta, use_container_width=True)

with tab4:
    st.subheader("Top Tracks (latest snapshot artists)")
    if tracks_df.empty or latest.empty:
        st.caption("No track data yet.")
    else:
        latest_names = latest["artist_name"].unique().tolist()
        tracks_latest = tracks_df[tracks_df["artist_name"].isin(latest_names)].copy()
        tracks_latest["timestamp"] = pd.to_datetime(tracks_latest["timestamp"], errors="coerce", utc=True)
        # show the most recent pull’s tracks (not historical trend)
        most_recent_pull = tracks_latest["timestamp"].max()
        recent_tracks = tracks_latest[tracks_latest["timestamp"] == most_recent_pull]
        show_cols = ["artist_name", "track_name", "track_popularity", "track_url", "timestamp"]
        have = [c for c in show_cols if c in recent_tracks.columns]
        if recent_tracks.empty:
            st.caption("No recent track snapshot.")
        else:
            st.dataframe(
                recent_tracks[have].sort_values(["artist_name", "track_popularity"], ascending=[True, False]),
                use_container_width=True
            )

# footer
st.caption("Last fetch: "
           f"{artists_df['timestamp'].max().strftime('%Y-%m-%d %H:%M:%S %Z') if not artists_df.empty else '—'} | "
           f"artist rows={len(artists_df):,} | tracks rows={len(tracks_df):,}")
