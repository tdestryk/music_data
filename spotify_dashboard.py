# spotify_dashboard.py
import csv
from datetime import timedelta
import pandas as pd
import plotly.express as px
import streamlit as st

# ---------- Page + Theme ----------
st.set_page_config(page_title="Spotify Artist Stats", layout="wide")

st.markdown("""
<style>
h1, h2, h3 { color: #1DB954; }
.stTabs [data-baseweb="tab"] { font-size: 16px; }
</style>
""", unsafe_allow_html=True)

st.markdown(
    "## <img src='https://upload.wikimedia.org/wikipedia/commons/1/19/Spotify_logo_without_text.svg' width='28'/> "
    "Spotify Artist Stats Dashboard",
    unsafe_allow_html=True,
)

# ---------- Data Loader ----------
@st.cache_data
def load_data() -> pd.DataFrame:
    try:
        df = pd.read_csv(
            "spotify_stats.csv",
            engine="python",
            on_bad_lines="skip",
            quotechar='"',
        )
        # timestamps
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"])
        else:
            df["timestamp"] = pd.NaT

        # ensure columns exist
        for col in ["artist_name", "followers", "popularity", "genres", "spotify_url"]:
            if col not in df.columns:
                df[col] = None

        # numeric
        df["followers"] = pd.to_numeric(df["followers"], errors="coerce")
        df["popularity"] = pd.to_numeric(df["popularity"], errors="coerce")

        # forward/back fill genres per artist so blanks get filled by last-known
        df = df.sort_values(["artist_name", "timestamp"])
        df["genres"] = df.groupby("artist_name")["genres"].ffill().bfill()

        return df.dropna(subset=["artist_name", "followers"])
    except Exception as e:
        st.error(f"Error loading CSV: {e}")
        return pd.DataFrame()

# reload button
top_cols = st.columns([1, 8, 1])
with top_cols[0]:
    if st.button("🔄 Reload data"):
        load_data.clear()
        st.experimental_rerun()

df = load_data()
if df.empty:
    st.warning("No data available to display.")
    st.stop()

# ---------- Controls ----------
all_artists = sorted(df["artist_name"].dropna().unique().tolist())
selected_artists = st.multiselect(
    "Choose artists to display",
    options=all_artists,
    default=all_artists,
)

hours = st.slider("Time window (hours)", min_value=1, max_value=168, value=24)
cutoff = pd.Timestamp.now() - timedelta(hours=hours)
view = df[(df["artist_name"].isin(selected_artists)) & (df["timestamp"] >= cutoff)].copy()

tabs = st.tabs(["📊 Current Stats Summary", "📈 Followers Over Time", "🧪 Compare Artists"])

# ---------- Enhance metrics for tiny changes ----------
if not view.empty:
    # friendlier scales
    view["followers_thousands"] = view["followers"] / 1_000
    view["followers_millions"] = view["followers"] / 1_000_000

    # proper ordering for diffs
    view = view.sort_values(["artist_name", "timestamp"])

    # deltas and percent change
    view["followers_delta"] = view.groupby("artist_name")["followers"].diff()
    view["followers_pct"] = view.groupby("artist_name")["followers"].pct_change() * 100

    # optional smoothing
    smooth = st.checkbox("Smooth to hourly averages", value=False, key="smooth_hourly")
    if smooth:
        view = (
            view.set_index("timestamp")
                .groupby("artist_name")
                .apply(lambda g: g.resample("1H").mean(numeric_only=True).ffill())
                .reset_index(level=0)
                .reset_index()
        )

# ---------- Tab 1: Current Stats ----------
with tabs[0]:
    st.subheader("📊 Current Stats Summary")
    if view.empty:
        st.info("No rows in the selected time range.")
    else:
        latest = view.sort_values("timestamp").groupby("artist_name").last().reset_index()
        for col in ["followers", "popularity", "genres", "spotify_url"]:
            if col not in latest.columns:
                latest[col] = None
        st.dataframe(
            latest[["artist_name", "followers", "popularity", "genres", "spotify_url"]],
            use_container_width=True,
        )

# ---------- Tab 2: Followers Over Time ----------
with tabs[1]:
    st.subheader("📈 Followers Over Time")
    if view.empty:
        st.info("No rows in the selected time range.")
    else:
        metric = st.radio(
            "Metric",
            ["Followers (millions)", "Followers (thousands)", "Δ Followers", "% Change", "Raw Followers"],
            horizontal=True,
        )
        y_col = {
            "Followers (millions)": "followers_millions",
            "Followers (thousands)": "followers_thousands",
            "Δ Followers": "followers_delta",
            "% Change": "followers_pct",
            "Raw Followers": "followers",
        }[metric]

        fig = px.line(
            view,
            x="timestamp",
            y=y_col,
            color="artist_name",
            markers=True,
            labels={"timestamp": "Date", y_col: metric},
        )

        # nice ticks
        if metric in ["Followers (millions)", "Followers (thousands)", "Raw Followers"]:
            fig.update_yaxes(tickformat="~s")
        if metric == "% Change":
            fig.update_yaxes(ticksuffix="%")

        # log option for raw followers
        if metric == "Raw Followers":
            if st.toggle("Use log scale", value=False, key="log_followers"):
                fig.update_yaxes(type="log")

        st.plotly_chart(fig, use_container_width=True)

# ---------- Tab 3: Compare Artists ----------
with tabs[2]:
    st.subheader("🧪 Compare Artists")
    if view.empty:
        st.info("No rows in the selected time range.")
    else:
        latest = view.sort_values("timestamp").groupby("artist_name").last().reset_index()
        earliest = view.sort_values("timestamp").groupby("artist_name").first().reset_index()

        # Join earliest to latest to compute change in the selected window
        change = latest[["artist_name", "followers", "popularity"]].merge(
            earliest[["artist_name", "followers"]].rename(columns={"followers": "followers_start"}),
            on="artist_name",
            how="left",
        )
        change["followers_delta"] = change["followers"] - change["followers_start"]
        change["followers_delta_pct"] = (change["followers_delta"] / change["followers_start"]) * 100

        # Bars
        c1, c2 = st.columns(2)
        with c1:
            fig1 = px.bar(
                change.sort_values("popularity", ascending=False),
                x="artist_name", y="popularity", color="artist_name",
                title="Current Popularity"
            )
            st.plotly_chart(fig1, use_container_width=True)
        with c2:
            fig2 = px.bar(
                change.sort_values("followers", ascending=False),
                x="artist_name", y="followers", color="artist_name",
                title="Current Followers"
            )
            fig2.update_yaxes(tickformat="~s")
            st.plotly_chart(fig2, use_container_width=True)

        st.caption("Change within the selected time window")
        st.dataframe(
            change[["artist_name", "followers", "followers_delta", "followers_delta_pct", "popularity"]],
            use_container_width=True,
        )
