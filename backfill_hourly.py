# backfill_hourly.py
import csv
from pathlib import Path
import pandas as pd

IN = Path("spotify_stats.csv")
OUT = Path("spotify_stats_backfilled.csv")

df = pd.read_csv(IN, engine="python", on_bad_lines="skip", quotechar='"')
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
df = df.dropna(subset=["artist_name", "timestamp"]).sort_values(["artist_name","timestamp"])
# resample hourly per artist with forward fill
res = (df.set_index("timestamp")
         .groupby("artist_name")
         .apply(lambda g: g.resample("1H").ffill())
         .drop(columns=["artist_name"])
         .reset_index())
res["is_backfill"] = 1
# write new file; you can rename to spotify_stats.csv after inspecting
res.to_csv(OUT, index=False, quoting=csv.QUOTE_ALL)
print(f"Backfilled to {OUT} (rows={len(res)})")
