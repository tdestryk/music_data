# spotify_dashboard.py
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

RUNS_LOG = Path("runs.log")
CSV_PATH = Path("spotify_stats.csv")
ALERT_THRESHOLD_PCT = 0.2  # alert if |Δ%| >= this within selected window

# ---------------- Page / Style ----------------
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

# ---------------- Header: Last fetch ----------------
def read_last_run():
    if not RUNS_LOG.exists():
        return None
    try:
        last = RUNS_LOG.read_text(encoding="utf-8").strip().splitlines()[-1]
        return last
    except Exception:
        return None

last = read_last_run()
if last:
    st.caption(f"Last fetch: `{last}`")
else:
    st.caption("Last fetch: unknown")

# ---------------- Data Loader ----------------
@st.cache_data
def load_data() -> pd.DataFrame:
    """
    Read CSV robustly, parse timestamps, make sure required columns exist,
    cast numeric types, and forward/back-fill genres per artist.
    """
    if not CSV_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(
        CSV_PATH,
        engine="python",
        on_bad_lines="skip",
        quotechar='"',
    )

    # Ensure columns exist
    for col in ["artist_name", "followers", "popularity", "genres", "spotify_url", "timestamp"]:
        if col not in df.columns:
            df[col] = None

    # Parse and clean timestamp
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp", "artist_name"])

    # Numeric casts
    df["followers"] = pd.to_numeric(df["followers"], errors="coerce")
    df["popularity"] = pd.to_numeric(df["popularity"], errors="coerce")
    df = df.dropna(subset=["followers"])  # must have followers

    # Sort for fills/diffs
    df = df.sort_values(["artist_name", "timestamp"])

    # Make genres sticky per artist
    df["genres"] = df.groupby("artist_name")["genres"].ffill().bfill()

    return df

# Reload button (clears cache)
top_cols = st.columns([1, 8, 1])
with top_cols[0]:
   if st.button("🔄 Reload data"):
    # clear the cached dataframe
    load_data.clear()
    try:
        st.rerun()                 # Streamlit ≥ 1.30
    except AttributeError:
        st.experimental_rerun()    # older Streamlit fallback

df = load_data()
if df.empty:
    st.warning("No data available to display.")
    st.stop()

# ---------------- Controls ----------------
all_artists = sorted(df["artist_name"].unique().tolist())
selected_artists = st.multiselect(
    "Choose artists to display",
    options=all_artists,
    default=all_artists,
)

hours = st.slider("Time window (hours)", min_value=1, max_value=168, value=24)
cutoff = pd.Timestamp.now(tz=df["timestamp"].dt.tz) - timedelta(hours=hours)

hide_backfill = "is_backfill" in df.columns and st.checkbox("Hide backfilled rows", value=True)
if hide_backfill and "is_backfill" in df.columns:
    df_view_base = df[df["is_backfill"] != 1]
else:
    df_view_base = df

view = df_view_base[
    (df_view_base["artist_name"].isin(selected_artists)) &
    (df_view_base["timestamp"] >= cutoff)
].copy()

# ---------------- Enhance metrics ----------------
if not view.empty:
    # Friendly scales
    view["followers_thousands"] = view["followers"] / 1_000
    view["followers_millions"] = view["followers"] / 1_000_000

    # Proper ordering for diffs
    view = view.sort_values(["artist_name", "timestamp"])

    # Deltas and percent change vs previous point
    view["followers_delta"] = view.groupby("artist_name")["followers"].diff()
    view["followers_pct"] = view.groupby("artist_name")["followers"].pct_change() * 100

    # Optional smoothing
    smooth = st.checkbox("Smooth to hourly averages", value=False, key="smooth_hourly")
    if smooth:
        view = (
            view.set_index("timestamp")
                .groupby("artist_name")
                .apply(lambda g: g.resample("1H").mean(numeric_only=True).ffill())
                .reset_index(level=0)
                .reset_index()
        )

# ---------------- In-app Alerts (Δ% over window) ----------------
if not view.empty:
    latest = view.sort_values("timestamp").groupby("artist_name").last().reset_index()
    earliest = view.sort_values("timestamp").groupby("artist_name").first().reset_index()
    win = latest[["artist_name", "followers"]].merge(
        earliest[["artist_name", "followers"]].rename(columns={"followers": "start"}),
        on="artist_name",
        how="left",
    )
    win["followers"] = pd.to_numeric(win["followers"], errors="coerce")
    win["start"] = pd.to_numeric(win["start"], errors="coerce")
    win = win.dropna(subset=["followers", "start"])
    win["pct"] = (win["followers"] - win["start"]) / win["start"] * 100
    tripped = win[win["pct"].abs() >= ALERT_THRESHOLD_PCT]

    if not tripped.empty:
        lines = [f"• **{r.artist_name}**: {r.pct:+.3f}% in window" for r in tripped.itertuples()]
        st.warning("🚨 Alert threshold reached:\n\n" + "\n".join(lines))

# ---------------- Tabs ----------------
tab1, tab2, tab3 = st.tabs(["📊 Current Stats Summary", "📈 Followers Over Time", "🧪 Compare Artists"])

# ---- Tab 1: Current Stats ----
with tab1:
    st.subheader("📊 Current Stats Summary")
    if view.empty:
        st.info("No rows in the selected time range.")
    else:
        latest = view.sort_values("timestamp").groupby("artist_name").last().reset_index()
        # Ensure display columns exist
        for col in ["followers", "popularity", "genres", "spotify_url"]:
            if col not in latest.columns:
                latest[col] = None
        st.dataframe(
            latest[["artist_name", "followers", "popularity", "genres", "spotify_url"]],
            use_container_width=True,
        )

# ---- Tab 2: Followers Over Time ----
with tab2:
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

        # Formatting
        if metric in ["Followers (millions)", "Followers (thousands)", "Raw Followers"]:
            fig.update_yaxes(tickformat="~s")
        if metric == "% Change":
            fig.update_yaxes(ticksuffix="%")

        # Optional log scale for raw followers
        if metric == "Raw Followers":
            if st.toggle("Use log scale", value=False, key="log_followers"):
                fig.update_yaxes(type="log")

        st.plotly_chart(fig, use_container_width=True)

# ---- Tab 3: Compare Artists ----
with tab3:
    st.subheader("🧪 Compare Artists")
    if view.empty:
        st.info("No rows in the selected time range.")
    else:
        latest = view.sort_values("timestamp").groupby("artist_name").last().reset_index()
        earliest = view.sort_values("timestamp").groupby("artist_name").first().reset_index()

        change = latest[["artist_name", "followers", "popularity"]].merge(
            earliest[["artist_name", "followers"]].rename(columns={"followers": "followers_start"}),
            on="artist_name",
            how="left",
        )
        change["followers_delta"] = change["followers"] - change["followers_start"]
        change["followers_delta_pct"] = (change["followers_delta"] / change["followers_start"]) * 100

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
