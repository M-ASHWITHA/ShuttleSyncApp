"""Write a synthetic historical boarding dataset: python scripts/generate_data.py data/history.csv"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shuttle.demand import generate_history, save_csv  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "data/history.csv"
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
rows = generate_history(days=90)
save_csv(rows, out)
print(f"wrote {len(rows)} rows to {out}")
