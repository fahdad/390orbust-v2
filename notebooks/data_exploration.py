# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # 390OrBust v2 — Data Exploration
#
# Quick-start notebook for fetching and inspecting bar data.

# %% Setup
from orbust.data.notebook import quick_fetch, summarize, check
from orbust.types import Timeframe

print("Notebook helpers loaded")

# %% Fetch recent data
df = quick_fetch(["XOM", "CVX", "COP"], days_back=3)
print(f"Fetched {len(df)} bars")

# %% Summary statistics
stats = summarize(df)

# %% Quality check
report = check(df, Timeframe.MINUTE_1)

# %% First few rows
df.head()

# %% Check available symbols and columns
print("Symbols:", sorted(set(c.rsplit("_", 1)[0] for c in df.columns if "_" in c)))
print("Columns:", list(df.columns[:7]))

# %% Quick price plot
_ = df[["XOM_close", "CVX_close", "COP_close"]].plot(
    title="Close Prices",
    figsize=(12, 5),
)
