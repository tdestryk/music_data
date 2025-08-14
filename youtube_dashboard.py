# youtube_dashboard.py
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
    page_title="YouTube Artist Stats",
    page_icon="📺",
    layout="wide",
)

PRIMARY = "#ff0000"            # YouTube red
ACCENT  = "#0f0f0f"

st.markdown(
    f"""
    <style>
    .stMetric > div > div > div {{ color: {PRIMARY}; }}
    .smallgray {{ color:#8a8a8a;font-size:12px }}
    .badge {{ display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;
              background:#f1f5f9;border:1px solid #e5e7eb;margin-left:6px }}
    .badge.green {{ background:#ecfdf5;border-color:#a7f3d0;color:#047857 }}
    .badge.red   {{ background:#fef2f2;border-color:#fecaca;color:#b91c1c }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- Config ----------
CHANNEL_CSV = "youtube_channel_stats.csv"
VIDEO_CSV   = "youtube_video_stats.csv"
ALERT_PCT   = 0.10  # 0.1% threshold shown as 0.001 in math, we’ll treat as 0.001 of 1.0

# ---------- Utils ----------
def _ensure_utc(series: pd.Series) -> pd.Series:
    """Make any datetime series tz-aware (UTC). If already tz-aware, convert to UTC."""
    if series.dt.tz is None:
        return series.dt.tz_localize("UTC")
    return series.dt.tz_convert("UTC")

@st.cache_data(show_spinner=False)
def load_channels() -> pd.DataFrame:
    if not os.path.exists(CHANNEL_CSV):
        return pd.DataFrame(
            columns=["artist_name","channel_id","channel_title","subs","views","video_count","timestamp"]
        )
    df = pd.read_csv(
        CHANNEL_CSV,
        parse_dates=["timestamp"],
        dtype={
            "artist_name":"string",
            "channel_id":"string",
            "channel_title":"string",
            "subs":"Int64",
            "views":"Int64",
            "video_count":"Int64",
        }
    )
    if "timestamp" in df.columns and not df.empty:
        df["timestamp"] = _ensure_utc(df["timestamp"])
    return df

@st.cache_data(show_spinner=False)
def load_videos() -> pd.DataFrame:
    if not os.path.exists(VIDEO_CSV):
        return pd.DataFrame(
            columns=["artist_name","channel_id","video_id","title","published_at","views","likes","comments","timestamp"]
        )
    df = pd.read_csv(
        VIDEO_CSV,
        parse_dates=["published_at", "timestamp"],
        dtype={
            "artist_name":"string",
            "channel_id":"string",
            "video_id":"string",
            "title":"string",
            "views":"Int64",
            "likes":"Int64",
            "comments":"Int64",
        }
    )
    if "timestamp" in df.columns and not df.empty:
        df["timestamp"]    = _ensure_utc(df["timestamp"])
    if "published_at" in df.columns and not df.empty:
        df["published_at"] = _ensure_utc(df["published_at"])
    return df

def filter_window(df: pd.DataFrame, col: str, hours: int) -> pd.DataFrame:
    if df.empty:
        return df
    now_utc = pd.Timestamp.now(tz="UTC")
    start   = now_utc - timedelta(hours=hours)
    # ensure UTC:
    df[col] = _ensure_utc(df[col])
    return df[(df[col] >= start) & (df[col] <= now_utc)].copy()

def pct_change(first, last) -> float:
    try:
        if first in [0, None, np.nan] or pd.isna(first):
            return np.nan
        return (last - first) / float(first)
    except Exception:
        return np.nan

# ---------- Data ----------
channels = load_channels()
videos   = load_videos()

# UI: selections
st.title("YouTube Artist Stats Dashboard")
left, mid, right = st.columns([2, 3, 2])

with left:
    if not channels.empty:
        default = sorted(channels["artist_name"].dropna().unique().tolist())
    else:
        default = []
    sel = st.multiselect(
        "Choose channels to display",
        options=sorted(channels["artist_name"].dropna().unique().tolist()),
        default=default,
        help="Pick one or more artists"
    )

with right:
    win = st.slider("Time window (hours)", min_value=6, max_value=168, value=48, step=1)

# quick header line
st.caption(
    f"Last fetch: "
    f"{(channels['timestamp'].max().strftime('%Y-%m-%d %H:%M:%S UTC') if not channels.empty else '—')} "
    f"| <span class='smallgray'>channels rows={len(channels):,} | video rows={len(videos):,}</span>",
    help=None,
)

# Reload button (safe rerun)
if st.button("🔄 Reload data", type="secondary"):
    load_channels.clear()
    load_videos.clear()
    try:
        st.rerun()
    except Exception:
        pass

# nothing to show?
if channels.empty:
    st.info("No channel stats found yet — run your fetch job first.")
    st.stop()

if not sel:
    st.warning("Select at least one artist.")
    st.stop()

# filtered data
wchan = filter_window(channels[channels["artist_name"].isin(sel)], "timestamp", win)
wvids = filter_window(videos[videos["artist_name"].isin(sel)], "timestamp", win)
wpubs = filter_window(videos[videos["artist_name"].isin(sel)], "published_at", win)  # for recent uploads

# KPI row
k1, k2, k3, k4 = st.columns(4)
if not wchan.empty:
    # take the latest row per artist for totals
    latest = wchan.sort_values("timestamp").groupby("artist_name").tail(1)
    k1.metric("Total Subscribers", f"{int(latest['subs'].fillna(0).sum()):,}")
    k2.metric("Total Views",       f"{int(latest['views'].fillna(0).sum()):,}")
else:
    k1.metric("Total Subscribers", "0")
    k2.metric("Total Views", "0")
k3.metric("Uploads in Window", f"{int(wpubs['video_id'].nunique() if not wpubs.empty else 0):,}")
k4.metric("Snapshots Captured", f"{int(wchan['timestamp'].nunique() if not wchan.empty else 0):,}")

# ---------- Tabs ----------
tab1, tab2, tab3, tab4 = st.tabs(["✨ Snapshot", "📈 Time Series", "📊 Growth by Channel", "🎞️ Top Videos"])

# ---------- Alerts (banner) ----------
if not wchan.empty:
    # earliest & latest per artist in window
    sorted_w = wchan.sort_values("timestamp")
    start_df = sorted_w.groupby("artist_name").head(1)
    end_df   = sorted_w.groupby("artist_name").tail(1)
    merged   = start_df[["artist_name","subs"]].merge(
        end_df[["artist_name","subs"]],
        on="artist_name",
        suffixes=("_start","_end")
    )
    merged["pct"] = merged.apply(lambda r: pct_change(r["subs_start"], r["subs_end"]), axis=1)
    alerts = merged[(~merged["pct"].isna()) & (merged["pct"].abs() >= ALERT_PCT/100.0)]
    if not alerts.empty:
        msg = " • ".join(
            f"{row.artist_name}: {row.pct*100:+.3f}%"
            for row in alerts.itertuples(index=False)
        )
        st.markdown(f"<div class='badge red'>Alert: Δ subs > {ALERT_PCT:.1f}% → {msg}</div>", unsafe_allow_html=True)

# ---------- Snapshot ----------
with tab1:
    st.subheader("Latest Channel Snapshot")

    if wchan.empty:
        st.info("No data in this time window.")
    else:
        latest = wchan.sort_values("timestamp").groupby("artist_name").tail(1)
        show = latest[["artist_name","channel_title","subs","views","video_count","timestamp"]]
        show = show.sort_values("artist_name")
        st.dataframe(show, use_container_width=True)

    st.markdown("#### Latest Uploads (per channel)")
    if wvids.empty:
        st.caption("No video snapshots in this window.")
    else:
        # most recent upload per channel (by published_at)
        last_up = (
            wvids.sort_values("published_at")
                 .groupby("artist_name")
                 .tail(1)
                 .sort_values("artist_name")
        )
        cols = st.columns(len(last_up) if len(last_up)>0 else 1)
        for idx, row in enumerate(last_up.itertuples(index=False)):
            with cols[idx % len(cols)]:
                st.markdown(f"**{row.artist_name}**")
                # thumbnail (best-effort: standard YouTube pattern if id looks like YouTube id)
                thumb = f"https://img.youtube.com/vi/{row.video_id}/hqdefault.jpg"
                st.image(thumb, use_container_width=True)
                st.caption(pd.to_datetime(row.published_at).strftime("%b %d, %Y %H:%M UTC"))
                url = f"https://www.youtube.com/watch?v={row.video_id}"
                st.markdown(f"[{row.title}]({url})")

# ---------- Time Series ----------
with tab2:
    st.subheader("Time Series")
    if wchan.empty:
        st.info("No channel data in this window.")
    else:
        # total subs over time per artist (line)
        line_subs = wchan.sort_values("timestamp")
        fig1 = px.line(
            line_subs,
            x="timestamp", y="subs", color="artist_name",
            title="Subscribers Over Time",
            labels={"timestamp":"timestamp","subs":"subs","artist_name":"channel"},
        )
        st.plotly_chart(fig1, use_container_width=True)

        # total views over time per artist (line)
        fig2 = px.line(
            line_subs,
            x="timestamp", y="views", color="artist_name",
            title="Total Channel Views Over Time",
            labels={"timestamp":"timestamp","views":"views","artist_name":"channel"},
        )
        st.plotly_chart(fig2, use_container_width=True)

        # upload cadence heatmap
        st.markdown("#### Upload cadence (weekday × hour)")
        if wvids.empty:
            st.caption("No videos in this window.")
        else:
            tmp = wvids.copy()
            tmp["weekday_idx"] = tmp["published_at"].dt.weekday
            tmp["hour"]        = tmp["published_at"].dt.hour
            weekday_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            tmp["weekday"]  = tmp["weekday_idx"].map(dict(enumerate(weekday_names)))
            counts = tmp.groupby(["weekday","hour"]).size().reset_index(name="uploads")
            counts["weekday"] = pd.Categorical(counts["weekday"], categories=weekday_names, ordered=True)
            counts = counts.sort_values(["weekday","hour"])
            figh = px.density_heatmap(
                counts,
                x="hour", y="weekday", z="uploads", histfunc="avg", color_continuous_scale="Blues",
                title="Uploads heatmap",
                labels={"hour":"hour (UTC)", "weekday":"weekday"}
            )
            st.plotly_chart(figh, use_container_width=True)

# ---------- Growth by Channel ----------
with tab3:
    st.subheader("Growth by Channel (Δ in window)")
    if wchan.empty:
        st.info("No channel data in this window.")
    else:
        sorted_w = wchan.sort_values("timestamp")
        start_df = sorted_w.groupby("artist_name").head(1)
        end_df   = sorted_w.groupby("artist_name").tail(1)
        g = start_df[["artist_name","subs","views"]].merge(
            end_df[["artist_name","subs","views"]],
            on="artist_name", suffixes=("_start","_end")
        )
        g["subs_change"]  = g["subs_end"]  - g["subs_start"]
        g["views_change"] = g["views_end"] - g["views_start"]
        g["subs_pct"]  = g.apply(lambda r: pct_change(r["subs_start"], r["subs_end"]), axis=1) * 100
        g["views_pct"] = g.apply(lambda r: pct_change(r["views_start"], r["views_end"]), axis=1) * 100

        figb = px.bar(
            g.sort_values("subs_change", ascending=False),
            x="artist_name", y="subs_change", color="subs_pct",
            color_continuous_scale="RdBu", title="Subscriber Change (absolute) — colored by % change",
            labels={"artist_name":"channel","subs_change":"Δ subscribers","subs_pct":"% change"}
        )
        st.plotly_chart(figb, use_container_width=True)

        st.dataframe(
            g[["artist_name","subs_start","subs_end","subs_change","subs_pct","views_start","views_end","views_change","views_pct"]]
            .sort_values("subs_change", ascending=False),
            use_container_width=True
        )

# ---------- Top Videos ----------
with tab4:
    st.subheader("Top Videos in Window")
    if wvids.empty:
        st.info("No video snapshots in this window.")
    else:
        topn = st.slider("Show top N by views", min_value=5, max_value=50, value=20, step=1)
        latest_video_view = (wvids.sort_values(["video_id","timestamp"]).groupby("video_id").tail(1))
        top = (
            latest_video_view.sort_values("views", ascending=False)
                             .head(topn)
                             [["artist_name","title","views","likes","comments","published_at","video_id","timestamp"]]
        )
        st.dataframe(top, use_container_width=True)
