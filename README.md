# ScarperTelegramData-CSI3

Script used for the Leo report (Polimi 2.0, Homework 3). It counts the questions asked per day in Telegram group exports.

## What it does

- Reads the JSON exports of Telegram Desktop.
- Counts a message as a question if it contains a "?" (links excluded) or starts with a typical question phrase. Messages under 3 words, forwarded messages and bot messages are ignored.
- Writes a daily CSV and two charts for each group, plus a summary.
- Can build a sample of messages to label by hand (`--campione`) and compute precision and recall (`--valuta`).

## Usage

```
pip install matplotlib
python3 questionCounter.py data/*.json -o risultati_v2
python3 questionCounter.py data/DSU.json -o risultati_v2 --campione 200
python3 questionCounter.py --valuta risultati_v2/DSU_campione.csv
```

## Data

The raw exports (`data/`) and the labelling samples (`*_campione.csv`) contain message text and are not published. `risultati_v2/` has only daily counts and charts.
