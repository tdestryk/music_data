# fetch_news.py
import os, time, csv, feedparser

ARTISTS = ["Bad Bunny","Foo Fighters","Kendrick Lamar","Taylor Swift","Weezer"]
OUT = "news.csv"

def feeds_for(q: str):
    q_enc = q.replace(" ", "+")
    # Google News RSS by query (worldwide)
    return [f"https://news.google.com/rss/search?q={q_enc}&hl=en-US&gl=US&ceid=US:en"]

def main():
    rows = []
    for name in ARTISTS:
        for url in feeds_for(name + " music"):
            d = feedparser.parse(url)
            for e in d.entries[:10]:  # take a few per feed
                rows.append({
                    "artist_name": name,
                    "title": e.get("title",""),
                    "link": e.get("link",""),
                    "published": e.get("published",""),
                    "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
                })
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["artist_name","title","link","published","fetched_at"])
        w.writeheader()
        w.writerows(rows)

if __name__ == "__main__":
    main()
