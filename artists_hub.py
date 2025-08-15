# artists_hub.py
from __future__ import annotations

import os
from typing import List, Dict, Iterable, Any, Tuple

import pandas as pd
import streamlit as st
import plotly.express as px

# ----------------- Page config -----------------
st.set_page_config(page_title="Artist Hub — Spotify + YouTube", layout="wide")
st.title("💿 Artist Hub — Spotify + YouTube")
st.caption("All times shown in **UTC**. Toggle Δ to see change; Auto-zoom tightens the y-axis to show small moves.")

SPOTIFY_CSV = "spotify_stats.csv"
YOUTUBE_CSV = "youtube_stats.csv"
LINKS_CSV   = "artist_links.csv"

# ----------------- Utilities -------------------
def _to_utc_series(s: pd.Series) -> pd.Series:
    """Make a pandas datetime Series UTC-aware, regardless of input mix."""
    dt = pd.to_datetime(s, utc=True, errors="coerce")
    # already tz-aware when utc=True; no tz_localize on dt
    return dt

def _filter_window(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    """Return only rows within `hours` of current UTC time."""
    if df.empty or "timestamp" not in df.columns:
        return df.copy()

    ts = _to_utc_series(df["timestamp"])
    df = df.assign(timestamp=ts)

    # Always make a tz-aware UTC "now" (do not tz_localize here)
    now = pd.Timestamp.now(tz="UTC")
    cut = now - pd.Timedelta(hours=hours)
    return df.loc[df["timestamp"] >= cut].copy()

def _first_val(df: pd.DataFrame, col: str):
    s = df[col].dropna()
    return s.iloc[0] if not s.empty else None

def _last_val(df: pd.DataFrame, col: str):
    s = df[col].dropna()
    return s.iloc[-1] if not s.empty else None

def compute_deltas(df: pd.DataFrame, value_cols: List[str], hours: int) -> pd.DataFrame:
    """For each artist, compute deltas for `value_cols` in the time window."""
    if df.empty:
        return pd.DataFrame(columns=["artist_name"] + [f"{c}_Δ" for c in value_cols])

    w = _filter_window(df.sort_values(["artist_name", "timestamp"]), hours)
    if w.empty:
        return pd.DataFrame(columns=["artist_name"] + [f"{c}_Δ" for c in value_cols])

    rows: List[Dict[str, Any]] = []
    for artist, g in w.groupby("artist_name", sort=False):
        g = g.sort_values("timestamp")
        row: Dict[str, Any] = {"artist_name": artist}
        for c in value_cols:
            if c not in g.columns:
                row[f"{c}_Δ"] = 0
                continue
            first_v = _first_val(g, c)
            last_v  = _last_val(g, c)
            if first_v is None or last_v is None:
                row[f"{c}_Δ"] = 0
            else:
                try:
                    row[f"{c}_Δ"] = int(last_v) - int(first_v)
                except Exception:
                    try:
                        row[f"{c}_Δ"] = float(last_v) - float(first_v)
                    except Exception:
                        row[f"{c}_Δ"] = 0
        rows.append(row)

    return pd.DataFrame(rows).fillna(0)

# ----------------- Links + Socials ------------
SOCIAL_KEYS = [
    ("spotify_url",   "🎧", "Spotify"),
    ("youtube_url",   "▶️", "YouTube"),
    ("facebook_url",  "📘", "Facebook"),
    ("instagram_url", "📸", "Instagram"),
    ("tiktok_url",    "🎵", "TikTok"),
    ("twitter_url",   "𝕏",  "X/Twitter"),
    ("website_url",   "🌐", "Website"),
]

def normalize_links_df(df: pd.DataFrame) -> pd.DataFrame:
    # Accept x_url → twitter_url
    if "x_url" in df.columns and "twitter_url" not in df.columns:
        df["twitter_url"] = df["x_url"]

    need_cols = {"artist_name", "image_url"} | {k for k, _, _ in SOCIAL_KEYS}
    for col in need_cols:
        if col not in df.columns:
            df[col] = ""

    for col in need_cols:
        df[col] = df[col].astype(str).str.strip()
        df.loc[df[col].isin(["", "nan", "None"]), col] = ""

    df = df.drop_duplicates(subset=["artist_name"], keep="last")
    return df[["artist_name", "image_url"] + [k for k, _, _ in SOCIAL_KEYS]]

def render_social_buttons(link_row: pd.Series):
    links = []
    for key, icon, label in SOCIAL_KEYS:
        url = str(link_row.get(key, "") or "").strip()
        if url.startswith("http"):
            links.append((f"{icon} {label}", url))
    if not links:
        st.caption("No social links yet.")
        return
    cols = st.columns(min(len(links), 6))
    for i, (label, url) in enumerate(links):
        with cols[i % len(cols)]:
            st.link_button(label, url)

# ----------------- Data loading -------------
def load_csv_safe(path: str, parse_dates: Iterable[str] | None = None) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        if parse_dates:
            for c in parse_dates:
                if c in df.columns:
                    df[c] = _to_utc_series(df[c])
        return df
    except Exception:
        return pd.DataFrame()

def latest_per_artist(df: pd.DataFrame, cols_keep: List[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["artist_name"] + cols_keep + ["timestamp"])
    if "timestamp" not in df.columns:
        df["timestamp"] = pd.NaT
    df = df.sort_values("timestamp")
    last = df.groupby("artist_name", as_index=False).tail(1)
    cols = ["artist_name"] + [c for c in cols_keep if c in last.columns] + ["timestamp"]
    return last[cols]

# ----------------- Chart helpers -------------
def _auto_range(y: pd.Series, pad_ratio: float = 0.05) -> Tuple[float, float] | None:
    y = pd.to_numeric(y, errors="coerce").dropna()
    if y.empty:
        return None
    lo, hi = float(y.min()), float(y.max())
    if lo == hi:
        # add a tiny band so it doesn't look flat-line squashed
        eps = max(1.0, abs(hi) * 0.02)
        return (lo - eps, hi + eps)
    pad = (hi - lo) * pad_ratio
    return (lo - pad, hi + pad)

def make_series_for_chart(df: pd.DataFrame, artists: List[str], value_col: str, show_delta: bool, hours: int) -> pd.DataFrame:
    if df.empty or "artist_name" not in df.columns or "timestamp" not in df.columns or value_col not in df.columns:
        return pd.DataFrame(columns=["artist_name", "timestamp", value_col])

    w = _filter_window(df, hours)
    w = w.loc[w["artist_name"].isin(artists)].copy()
    w = w.sort_values(["artist_name", "timestamp"])

    if show_delta:
        # group diff per artist
        w[value_col] = pd.to_numeric(w[value_col], errors="coerce")
        w[value_col] = w.groupby("artist_name", group_keys=False)[value_col].diff().fillna(0)
    return w[["artist_name", "timestamp", value_col]]

def line_chart(df: pd.DataFrame, y_col: str, title: str, auto_zoom: bool):
    if df.empty:
        st.info("No data to chart for the current selection/window.")
        return
    fig = px.line(
        df, x="timestamp", y=y_col, color="artist_name",
        labels={"timestamp": "Time (UTC)", y_col: y_col.replace("_", " ")},
        template="plotly_dark"
    )
    if auto_zoom:
        rng = _auto_range(df[y_col])
        if rng:
            fig.update_yaxes(range=list(rng))
    fig.update_layout(legend_title_text="Artist", margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True, theme="streamlit")

# ----------------- Sidebar controls ---------
with st.sidebar:
    st.write("All times shown in UTC.")
    hours = st.slider("Time window (hours)", min_value=24, max_value=240, value=72, step=1)
    show_delta = st.toggle("Show Δ change", value=False)
    auto_zoom = st.toggle("Auto-zoom y-axis", value=False)

# ----------------- Load data ----------------
links_raw = load_csv_safe(LINKS_CSV)
if links_raw.empty or "artist_name" not in links_raw.columns:
    st.error("`artist_links.csv` missing or malformed (needs at least `artist_name`).")
    st.stop()
links_df = normalize_links_df(links_raw)

s_df = load_csv_safe(SPOTIFY_CSV, parse_dates=["timestamp"])
y_df = load_csv_safe(YOUTUBE_CSV, parse_dates=["timestamp"])

if "artist_name" not in s_df.columns:
    s_df["artist_name"] = ""
if "artist_name" not in y_df.columns:
    y_df["artist_name"] = ""

artists_all = links_df["artist_name"].tolist()
default_pick = [a for a in ["Bad Bunny", "Kendrick Lamar", "Taylor Swift", "Foo Fighters"] if a in artists_all]
pick = st.sidebar.multiselect("Artists", artists_all, default=default_pick) or artists_all

# ----------------- Deltas (summary tables) ---
s_delta_cols = ["followers", "popularity"]
y_delta_cols = ["subscribers", "views"]

s_deltas = compute_deltas(s_df, s_delta_cols, hours)
y_deltas = compute_deltas(y_df, y_delta_cols, hours)

# ----------------- Latest snapshots ---------
s_latest = latest_per_artist(s_df, ["followers", "popularity", "image_url"])
y_latest = latest_per_artist(y_df, ["subscribers", "views"])

latest = links_df.merge(s_latest, on="artist_name", how="left") \
                 .merge(y_latest, on="artist_name", how="left", suffixes=("_s", "_y"))

# ----------------- Δ tables -----------------
st.subheader("Δ in Last 7 Days (Spotify) ↩️")
s_view = s_deltas[s_deltas["artist_name"].isin(pick)].copy()
s_view = s_view.rename(columns={"followers_Δ": "followers_Δ7d", "popularity_Δ": "popularity_Δ7d"})
st.dataframe(s_view.fillna(0), use_container_width=True, hide_index=True)

st.subheader("Δ in Last 7 Days (YouTube) ↪️")
y_view = y_deltas[y_deltas["artist_name"].isin(pick)].copy()
y_view = y_view.rename(columns={"subscribers_Δ": "subs_Δ7d", "views_Δ": "views_Δ7d"})
st.dataframe(y_view.fillna(0), use_container_width=True, hide_index=True)

# ----------------- Charts --------------------
st.markdown("### Followers Over Time (Spotify)" if not show_delta else "### Δ Followers Over Time (Spotify)")
s_series = make_series_for_chart(s_df, pick, "followers", show_delta, hours)
line_chart(s_series.rename(columns={"followers": "value"}), "value", "Spotify", auto_zoom)

st.markdown("### YouTube Over Time")
yt_metric = st.segmented_control(
    "Metric",
    options=["subscribers", "views"],
    selection_mode="single",
    default="subscribers",
)
y_series = make_series_for_chart(y_df, pick, yt_metric, show_delta, hours)
line_chart(y_series.rename(columns={yt_metric: "value"}), "value", "YouTube", auto_zoom)

# ----------------- Latest w/ links ----------
st.subheader("Latest Snapshot (with links)")
snap = latest[latest["artist_name"].isin(pick)].copy()

for key, _, _ in SOCIAL_KEYS:
    if key in snap.columns:
        snap[key] = snap[key].astype(str).where(snap[key].astype(str).str.startswith("http"), "")

col_config = {
    "spotify_url":   st.column_config.LinkColumn("Spotify"),
    "youtube_url":   st.column_config.LinkColumn("YouTube"),
    "facebook_url":  st.column_config.LinkColumn("Facebook"),
    "instagram_url": st.column_config.LinkColumn("Instagram"),
    "tiktok_url":    st.column_config.LinkColumn("TikTok"),
    "twitter_url":   st.column_config.LinkColumn("X/Twitter"),
    "website_url":   st.column_config.LinkColumn("Website"),
}

# give the two timestamps distinct names for readability in table
if "timestamp_s" not in snap.columns and "timestamp_x" in snap.columns:
    snap = snap.rename(columns={"timestamp_x": "timestamp_s"})
if "timestamp_y" not in snap.columns and "timestamp_y" in snap.columns:
    pass  # already correct

show_cols = ["artist_name", "followers", "popularity", "subscribers", "views", "timestamp_s", "timestamp_y"] \
            + [k for k,_,_ in SOCIAL_KEYS if k in snap.columns]

st.dataframe(
    snap.reindex(columns=[c for c in show_cols if c in snap.columns]).fillna(""),
    use_container_width=True,
    hide_index=True,
    column_config=col_config,
)

# ----------------- Cards --------------------
st.subheader("Cards")

for artist in pick:
    link_row_df = links_df.loc[links_df["artist_name"].eq(artist)]
    link_row = (link_row_df.iloc[0] if not link_row_df.empty else pd.Series())

    s_row_df = s_latest.loc[s_latest["artist_name"].eq(artist)]
    s_row = (s_row_df.iloc[0] if not s_row_df.empty else pd.Series())

    y_row_df = y_latest.loc[y_latest["artist_name"].eq(artist)]
    y_row = (y_row_df.iloc[0] if not y_row_df.empty else pd.Series())

    card = st.container(border=True)
    with card:
        c1, c2 = st.columns([1, 2])

        with c1:
            img = str(link_row.get("image_url", "") or "").strip()
            if img.startswith("http"):
                st.image(img, use_container_width=True)
            st.markdown(f"### {artist}")
            render_social_buttons(link_row)

        with c2:
            st.markdown("**Spotify**")
            if "followers" in s_row:
                st.metric("Followers", f"{int(s_row.get('followers') or 0):,}")
            if "popularity" in s_row:
                st.metric("Popularity (0–100)", int(s_row.get("popularity") or 0))

            st.markdown("**YouTube**")
            if "subscribers" in y_row:
                st.metric("Subscribers", f"{int(y_row.get('subscribers') or 0):,}")
            if "views" in y_row:
                st.metric("Views", f"{int(y_row.get('views') or 0):,}")

# ----------------- Footer -------------------
st.caption("Tip: if a row is missing, check that the artist name matches exactly in `artist_links.csv` and that a recent fetch wrote rows into the stats CSVs.")
