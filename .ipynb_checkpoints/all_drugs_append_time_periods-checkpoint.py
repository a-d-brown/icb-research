import pandas as pd

# Load files
df_main = pd.read_csv("All Drugs - Latest month vs 12m ago.csv")
df_list = pd.read_csv("List Sizes by ICB.csv")

# Keep only required columns from list size file
df_list = df_list[["ICB plus Code", "Year Month", "List Size"]]

# Merge on BOTH columns
df_merged = df_main.merge(
    df_list,
    on=["ICB plus Code", "Year Month"],
    how="left"
)

# Save result
df_merged.to_csv(
    "All Drugs National.csv",
    index=False
)

print("Merge complete.")