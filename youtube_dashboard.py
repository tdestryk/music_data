# youtube_dashboard.py
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="YouTube Artist Stats Dashboard", layout="wide")

CHAN_CSV = "youtube_channel_stats.csv"
VID_CSV = "youtube_video_stats.csv"

DEFAULT_BRANCH = os.getenv("GITHUB_DEFAULT_BRANCH", "main")
DEFAULT_REPO = os.getenv("GITHUB_REPOSITORY", "")  # e.g., "tdestryk/music_data"


def _raw_url(path: str) -> Optional[str]:
    if not DEFAULT_REPO:
        return None
    return f"https://raw.githubusercontent.com/{DEFAULT_REPO}/{DEFAULT_BRANCH}/{path}"


@st.cache_data(show_spinner=False, ttl=60)
def load_csv(path: str) -> pd.DataFrame:
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
    return pd.to_datetime(series, utc=True, errors="coerce")


def filter_window(df: pd.DataFrame, hours: int, ts_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df[ts_col] = parse_ts(df[ts_col])
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return df.loc[(df[ts_col] >= start) & (df[ts_col] <= end)]


# Load
channels_raw = load_csv(CHAN_CSV)
videos_raw = load_csv(VID_CSV)

# Normalize expected columns
if not channels_raw.empty:
    for c in ["artist_name", "channel_id", "channel_title", "subs", "views", "video_count", "timestamp"]:
        if c not in channels_raw.columns:
            channels_raw[c] = pd.NA

if not videos_raw.empty:
    for c in ["artist_name", "channel_id", "video_id", "title", "published_at", "views", "likes", "comments", "timestamp"]:
        if c not in videos_raw.columns:
            videos_raw[c] = pd.NA

# Header
st.markdown("## 📺 YouTube Artist Stats Dashboard")

last_ts = (
    parse_ts(channels_raw["timestamp"]).max().strftime("%Y-%m-%d %H:%M:%S UTC")
    if not channels_raw.empty else "—"
)
st.caption(
    f"Last fetch: **{last_ts}** | channels rows={len(channels_raw)} | video rows={len(videos_raw)}"
)

# Controls
default_artists = ["Bad Bunny", "Foo Fighters", "KendrickLamarVEVO", "Taylor Swift", "weezer"]
all_channels = sorted(channels_raw["artist_name"].dropna().unique().tolist()) if not channels_raw.empty else default_artists

left, right = st.columns([3, 1])
with left:
    selected = st.multiselect(
        "Choose channels to display",
        options=all_channels,
        default=[a for a in default_artists if a in all_channels] or all_channels[:5],
    )
with right:
    hours = st.slider("Time window (hours)", 6, 336, 48, step=6)

st.button("🔁 Reload data", on_click=lambda: st.cache_data.clear())

# Window frames
ch = filter_window(channels_raw, hours, ts_col="timestamp")
vd = filter_window(videos_raw, hours, ts_col="timestamp")

if not selected:
    st.info("No channels selected.")
    st.stop()

wch = ch[ch["artist_name"].isin(selected)]

# KPIs
k1, k2, k3, k4 = st.columns(4)
if wch.empty:
    st.warning("No channel snapshots found in this time window.")
else:
    latest = (
        wch.sort_values("timestamp")
           .groupby("artist_name", as_index=False)
           .tail(1)
           .reset_index(drop=True)
    )
    with k1:
        st.metric("Total Subscribers", f"{int(latest['subs'].fillna(0).sum()):,}")
    with k2:
        st.metric("Total Views", f"{int(latest['views'].fillna(0).sum()):,}")
    with k3:
        uploads_in_window = int(vd[vd["artist_name"].isin(selected)]["video_id"].nunique()) if not vd.empty else 0
        st.metric("Uploads in Window", f"{uploads_in_window:,}")
    with k4:
        st.metric("Snapshots Captured", f"{len(wch):,}")

# Tabs
t1, t2, t3, t4 = st.tabs(["📋 Snapshot", "📈 Time Series", "📹 Top Videos", "📊 Aggregates"])

# Snapshot
with t1:
    st.subheader("Latest Channel Snapshot")
    if wch.empty:
        st.caption("No data in window.")
    else:
        show = latest[["artist_name", "channel_title", "subs", "views", "video_count", "timestamp"]].copy()
        st.dataframe(show.set_index("artist_name"), use_container_width=True)

# Time Series
with t2:
    st.subheader("Subscribers Over Time (hourly)")
    if wch.empty:
        st.caption("No data in window.")
    else:
        s = wch.sort_values("timestamp")
        fig = px.line(
            s,
            x="timestamp",
            y="subs",
            color="artist_name",
            markers=True,
            labels={"timestamp": "timestamp (UTC)", "subs": "subs"}
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Total Channel Views Over Time (hourly)")
    if wch.empty:
        st.caption("No data in window.")
    else:
        v = wch.sort_values("timestamp")
        fig2 = px.line(
            v,
            x="timestamp",
            y="views",
            color="artist_name",
            markers=True,
            labels={"timestamp": "timestamp (UTC)", "views": "views"}
        )
        st.plotly_chart(fig2, use_container_width=True)

# Top Videos (window)
with t3:
    st.subheader("Top Videos in Window (by views)")
    vwin = vd[vd["artist_name"].isin(selected)].copy()
    if vwin.empty:
        st.caption("No videos in this window.")
    else:
        # safe published
        vwin["published_at"] = pd.to_datetime(vwin["published_at"], utc=True, errors="coerce")
        vwin = vwin.sort_values(["views"], ascending=False)
        show_cols = ["artist_name", "title", "views", "likes", "comments", "published_at", "video_id", "timestamp"]
        show_cols = [c for c in show_cols if c in vwin.columns]
        st.dataframe(vwin[show_cols], use_container_width=True, height=520)

        st.markdown("### Most Recent Upload (all-time, by published date)")
        # most recent per artist across all videos you have (not just window)
        if videos_raw.empty:
            st.caption("No video data yet.")
        else:
            all_latest = (
                videos_raw.sort_values("published_at")
                          .groupby("artist_name", as_index=False)
                          .tail(1)
                          .sort_values("artist_name")
            )
            cols = st.columns(max(1, min(4, len(all_latest))))
            for i, row in enumerate(all_latest.itertuples(index=False)):
                with cols[i % len(cols)]:
                    st.markdown(f"**{row.artist_name}**")
                    thumb = f"https://img.youtube.com/vi/{row.video_id}/hqdefault.jpg"
                    st.image(thumb, use_container_width=True)
                    ts_str = pd.to_datetime(row.published_at, utc=True, errors="coerce")
                    when = ts_str.strftime("%b %d, %Y %H:%M UTC") if pd.notna(ts_str) else "—"
                    st.caption(when)
                    url = f"https://www.youtube.com/watch?v={row.video_id}"
                    st.markdown(f"[{row.title}]({url})")

# Aggregates
with t4:
    st.subheader("Uploads per Day (window)")
    vwin = vd[vd["artist_name"].isin(selected)].copy()
    if vwin.empty:
        st.caption("No videos in window.")
    else:
        vwin["published_at"] = pd.to_datetime(vwin["published_at"], utc=True, errors="coerce")
        vwin["date"] = vwin["published_at"].dt.date
        agg = vwin.groupby(["artist_name", "date"], as_index=False)["video_id"].nunique()
        fig = px.bar(
            agg,
            x="date",
            y="video_id",
            color="artist_name",
            barmode="group",
            labels={"video_id": "uploads"},
        )
        st.plotly_chart(fig, use_container_width=True)
