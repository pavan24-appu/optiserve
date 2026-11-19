"""Writes datasets/case<N>_<slug>.csv (base) and ..._aug.csv (augmented). Run: python make_datasets.py"""
import os, re
from scenarios import SCENARIOS, build, augment
os.makedirs("datasets", exist_ok=True)
for c, (title, *_rest) in SCENARIOS.items():
    df, _ = build(c); slug = re.sub(r"\W+", "_", title.lower()).strip("_")
    df.to_csv(f"datasets/case{c}_{slug}.csv", index=False)
    augment(df, seed=c).to_csv(f"datasets/case{c}_{slug}_aug.csv", index=False)
print("done")
