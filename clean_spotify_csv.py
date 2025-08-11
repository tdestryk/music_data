import csv

input_file = "spotify_stats.csv"
output_file = "spotify_stats_clean.csv"

expected_columns = 5

with open(input_file, "r", encoding="utf-8") as infile, open(output_file, "w", newline="", encoding="utf-8") as outfile:
    reader = csv.reader(infile)
    writer = csv.writer(outfile)

    for i, row in enumerate(reader, start=1):
        if len(row) == expected_columns:
            writer.writerow(row)
        else:
            print(f"⚠️ Skipping line {i}: {len(row)} fields instead of {expected_columns} -> {row}")
