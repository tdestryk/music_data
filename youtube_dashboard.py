# youtube_dashboard.py
# Streamlit dashboard for YouTube channel stats
# - Robust UTC window filtering
# - Graceful handling when CSVs are empty/missing
# - Tabs: Snapshot • Time Series • Growth by Channel • Top Videos • Aggregates
# - Latest upload cards + upload cadence heatmap

import os
import json
import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from pathlib import Path

st.set_page_config(page_title="YouTube Artist Stats", page_icon="📺", layout="wide")

DATA_DIR = Path(".")
CHAN_CSV   = DATA_DIR / "youtube_channel_stats.csv"   # artist_name,channel_id,channel_title,subs,views,video_count,timestamp
VIDEO_CSV  = DATA_DIR / "youtube_video_stats.csv"     # artist_name,channel_id,video_id,title,published_at,views,likes,comments,timestamp
SOCIALS_JSON = DATA_DIR / "socials.json"              # optional

# ---------- helpers

def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        df = pd.read_csv(path, on_bad_lines="skip", engine="python")
    return df

def _parse_timestamp_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")

def filter_window(df: pd.DataFrame, hours: int, ts_col: str) -> pd.DataFrame:
    if df.empty or ts_col not in df.columns:
        return df
    ts = _parse_timestamp_utc(df[ts_col])
    df = df.assign(_ts=ts).dropna(subset=["_ts"])
    end = pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(hours=hours)
    return df[(df["_ts"] >= start) & (df["_ts"] <= end)].drop(columns=["_ts"])

@st.cache_data(show_spinner=False)
def load_youtube() -> tuple[pd.DataFrame, pd.DataFrame]:
    chans = _safe_read_csv(CHAN_CSV)
    vids  = _safe_read_csv(VIDEO_CSV)

    if not chans.empty:
        # normalize
        if "timestamp" in chans.columns:
            chans["timestamp"] = _parse_timestamp_utc(chans["timestamp"])
        for c in ["subs","views","video_count"]:
            if c in chans.columns:
                chans[c] = pd.to_numeric(chans[c], errors="coerce")

        # unify a "channel" display column
        if "channel_title" in chans.columns:
            chans["channel"] = chans["channel_title"]
        elif "channel" not in chans.columns:
            chans["channel"] = chans.get("artist_name", pd.Series(dtype=str))

    if not vids.empty:
        # two time-like columns: published_at (video publish), timestamp (snapshot)
        if "timestamp" in vids.columns:
            vids["timestamp"] = _parse_timestamp_utc(vids["timestamp"])
        if "published_at" in vids.columns:
            vids["published_at"] = _parse_timestamp_utc(vids["published_at"])

        for c in ["views","likes","comments"]:
            if c in vids.columns:
                vids[c] = pd.to_numeric(vids[c], errors="coerce")

    return chans, vids

def load_socials() -> dict:
    if SOCIALS_JSON.exists():
        try:
            return json.loads(SOCIALS_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def latest_per_group(df: pd.DataFrame, group: list[str], time_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values(time_col).groupby(group).tail(1)

# ---------- UI header

st.markdown("## 📺 YouTube Artist Stats Dashboard")

hdr_left, hdr_right = st.columns([1,1])
with hdr_left:
    if st.button("🔁 Reload data", use_container_width=False):
        st.cache_data.clear()
        st.rerun()

# ---------- load data

channels_df, videos_df = load_youtube()
socials = load_socials()

all_channels = sorted(channels_df["channel"].dropna().unique().tolist() if "channel" in channels_df.columns else [])
if not all_channels:
    st.warning("No YouTube data yet. Trigger your **Fetch YouTube** workflow, then reload.")
    st.stop()

selected = st.multiselect("Choose channels to display", options=all_channels, default=all_channels)
win = st.slider("Time window (hours)", 6, 168, 72)

w_channels = filter_window(channels_df[channels_df["channel"].isin(selected)], win, "timestamp")
w_videos   = filter_window(videos_df[videos_df["artist_name"].isin(channels_df[channels_df['channel'].isin(selected)]['artist_name'])] if not videos_df.empty and "artist_name" in videos_df.columns and "artist_name" in channels_df.columns else videos_df, win, "timestamp")

# quick header metrics
m1, m2, m3, m4 = st.columns(4)
if w_channels.empty:
    m1.metric("Total Subscribers", "0")
    m2.metric("Total Views", "0")
    m3.metric("Uploads in Window", "0")
    m4.metric("Snapshots Captured", "0")
else:
    latest_ch = latest_per_group(w_channels, ["channel"], "timestamp")
    m1.metric("Total Subscribers", f"{int(latest_ch['subs'].fillna(0).sum()):,}")
    m2.metric("Total Views", f"{int(latest_ch['views'].fillna(0).sum()):,}")
    m3.metric("Uploads in Window", f"{0 if w_videos.empty else w_videos['video_id'].nunique():,}")
    m4.metric("Snapshots Captured", f"{w_channels.shape[0]:,}")

# ---------- Tabs
tabA, tabB, tabC, tabD, tabE = st.tabs(["✨ Snapshot", "⏱️ Time Series", "📈 Growth by Channel", "🎬 Top Videos", "📦 Aggregates"])

with tabA:
    st.subheader("Latest Channel Snapshot")
    if w_channels.empty:
        st.info("No channel rows in this time window.")
    else:
        latest = latest_per_group(w_channels, ["channel"], "timestamp")
        show = [c for c in ["channel","subs","views","video_count","timestamp"] if c in latest.columns]
        st.dataframe(latest[show].sort_values("subs", ascending=False), use_container_width=True)

    st.markdown("---")
    st.markdown("#### Most Recent Upload (all-time, by published date)")
    if videos_df.empty:
        st.caption("No video data yet.")
    else:
        all_latest = (
            videos_df.dropna(subset=["published_at"])
                     .sort_values("published_at")
                     .groupby("artist_name", as_index=False)
                     .tail(1)
                     .sort_values("artist_name")
        )
        if all_latest.empty:
            st.caption("No parsed published times yet.")
        else:
            n = min(len(all_latest), 4)
            cols = st.columns(n if n>0 else 1)
            for i, row in enumerate(all_latest.itertuples(index=False)):
                with cols[i % n]:
                    st.markdown(f"**{row.artist_name}**")
                    thumb = f"https://img.youtube.com/vi/{row.video_id}/hqdefault.jpg"
                    st.image(thumb, use_container_width=True)
                    when = pd.to_datetime(row.published_at).tz_convert("UTC").strftime("%b %d, %Y %H:%M UTC")
                    st.caption(when)
                    url = f"https://www.youtube.com/watch?v={row.video_id}"
                    st.markdown(f"[{row.title}]({url})")

    st.markdown("---")
    st.markdown("#### Upload cadence (weekday × hour, from published_at)")
    if videos_df.empty or videos_df["published_at"].dropna().empty:
        st.caption("No publish times yet.")
    else:
        heat = videos_df.dropna(subset=["published_at"]).copy()
        heat["weekday"] = heat["published_at"].dt.tz_convert("UTC").dt.weekday  # 0=Mon
        heat["hour"]    = heat["published_at"].dt.tz_convert("UTC").dt.hour
        pivot = heat.pivot_table(index="weekday", columns="hour", values="video_id", aggfunc="count", fill_value=0)
        # reorder rows Mon..Sun
        pivot = pivot.reindex(index=[0,1,2,3,4,5,6])
        fig = px.imshow(
            pivot,
            labels=dict(x="Hour (UTC)", y="Weekday (0=Mon)", color="Uploads"),
            aspect="auto",
            color_continuous_scale="Blues"
        )
        fig.update_layout(height=360, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)

with tabB:
    st.subheader("Time Series")
    if w_channels.empty:
        st.info("No channel rows in this time window.")
    else:
        ts = w_channels.copy()
        ts["time"] = ts["timestamp"].dt.tz_convert("UTC")

        left, right = st.columns(2)

        with left:
            fig1 = px.line(
                ts.sort_values("time"),
                x="time", y="subs", color="channel",
                labels={"time":"Time (UTC)","subs":"Subscribers","channel":"Channel"},
            )
            fig1.update_layout(height=380, margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig1, use_container_width=True)

        with right:
            fig2 = px.line(
                ts.sort_values("time"),
                x="time", y="views", color="channel",
                labels={"time":"Time (UTC)","views":"Views","channel":"Channel"},
            )
            fig2.update_layout(height=380, margin=dict(l=10,r=10,t=10,b=10))
            st.plotly_chart(fig2, use_container_width=True)

    st.markdown("#### Uploads per day (in window)")
    if w_videos.empty or "published_at" not in w_videos.columns:
        st.caption("No uploads in this window.")
    else:
        per_day = (
            w_videos.dropna(subset=["published_at"])
                    .assign(day=w_videos["published_at"].dt.tz_convert("UTC").dt.date)
                    .groupby("day", as_index=False)
                    .agg(uploads=("video_id","nunique"))
        )
        fig = px.bar(per_day, x="day", y="uploads", labels={"day":"Day (UTC)","uploads":"Uploads"})
        fig.update_layout(height=300, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)

with tabC:
    st.subheader("Growth by Channel (Subscribers Δ in window)")
    if w_channels.empty:
        st.info("No data in this window.")
    else:
        seq = w_channels.sort_values(["channel","timestamp"])
        first = seq.groupby("channel", as_index=False).first(numeric_only=True)
        last  = seq.groupby("channel", as_index=False).last(numeric_only=True)

        comp = last[["channel","subs"]].merge(first[["channel","subs"]], on="channel", suffixes=("_last","_first"))
        comp["delta"] = comp["subs_last"] - comp["subs_first"]
        comp["pct"] = np.where(comp["subs_first"]>0, comp["delta"]/comp["subs_first"], np.nan)

        fig = px.bar(comp.sort_values("delta", ascending=False),
                     x="channel", y="delta", color="pct",
                     color_continuous_scale="RdBu",
                     labels={"channel":"Channel","delta":"Δ Subscribers","pct":"% change"})
        fig.update_layout(height=420, margin=dict(l=10,r=10,t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)

with tabD:
    st.subheader("Top Videos in Window")
    if w_videos.empty:
        st.info("No video rows in this window.")
    else:
        # pick top N by views at last snapshot per video
        last_vid = (
            w_videos.sort_values("timestamp")
                    .groupby("video_id", as_index=False)
                    .tail(1)
        )
        topN = st.slider("Show top N by views", 5, 50, 25)
        show_cols = ["channel_id","artist_name","title","views","likes","comments","published_at","video_id","timestamp"]
        show_cols = [c for c in show_cols if c in last_vid.columns]
        top = last_vid.sort_values("views", ascending=False).head(topN)[show_cols]
        st.dataframe(top, use_container_width=True, height=500)

with tabE:
    st.subheader("Aggregates")
    if w_channels.empty:
        st.info("No data in this window.")
    else:
        agg = (
            w_channels.groupby("channel", as_index=False)
                      .agg(
                          snapshots=("channel", "count"),
                          latest_subs=("subs","last"),
                          latest_views=("views","last"),
                          min_subs=("subs","min"),
                          max_subs=("subs","max"),
                      )
        )
        agg["subs_range"] = agg["max_subs"] - agg["min_subs"]
        st.dataframe(agg.sort_values("latest_subs", ascending=False), use_container_width=True)
