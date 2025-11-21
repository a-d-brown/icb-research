import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from functools import reduce

st.set_page_config(page_title="ePACT2 Dashboard Data Compiler", layout="centered")
st.title("ePACT2 Dashboard Data Compiler")

st.markdown("""
This tool compiles local and national CSVs from the ePACT2 dashboard into a single Excel file suitable for plotting as a time-series with lines for SICBL, ICB, and National data.
""")

st.markdown("""
1. Upload local and national CSV files separately.
Each file must include columns for:
- `Commissioner / Provider` or `Country`
- `Month`
- `Numerator`, `Denominator` (for local) or `Value` (for national)
""")

# Uploads
local_files = st.file_uploader("Upload LOCAL datasets", type="csv", accept_multiple_files=True)
national_files = st.file_uploader("Upload NATIONAL datasets", type="csv", accept_multiple_files=True)

# Column name entry
local_labels = []
national_labels = []

st.markdown("""
2. Enter the matching percentage column name for each file. If a local and national file share the same column name, they will be merged into a single output sheet.
""")

st.markdown("### Column names for LOCAL files")
for i, file in enumerate(local_files):
    local_labels.append(st.text_input(f"Local file '{file.name}' column name:", f"Metric {i+1} (%)"))

st.markdown("### Column names for NATIONAL files")
for i, file in enumerate(national_files):
    national_labels.append(st.text_input(f"National file '{file.name}' column name:", f"Metric {i+1} (%)"))

# Mapping
organisation_legend_mapping = {
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 84H': 'Durham',
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 00P': 'Sunderland',
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 00L': 'Northumberland',
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 01H': 'North Cumbria',
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 13T': 'Newcastle-Gateshead',
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 16C': 'Tees Valley',
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 99C': 'North Tyneside',
    'NHS NORTH EAST AND NORTH CUMBRIA ICB - 00N': 'South Tyneside',
    'ENGLAND': 'England'
}

# Cleaning and processing

def clean_local(df, pct_col):
    if 'Practice plus Code' in df.columns:
        df = df[~df['Practice plus Code'].str.contains(r'\( ?[CD] ?\d', na=False)]
    df = df.drop(columns=['Practice plus Code', 'Comparator Description', 'Age Band', 'Value'], errors='ignore')
    df['Month'] = pd.to_datetime(df['Month'], format='%b-%y', errors='coerce')
    df['Commissioner / Provider'] = df['Commissioner / Provider'].replace(organisation_legend_mapping)
    df = df.groupby(['Commissioner / Provider', 'Month'], as_index=False).sum()
    icb = df.groupby('Month')[['Numerator', 'Denominator']].sum().reset_index()
    icb['Commissioner / Provider'] = 'North East and North Cumbria'
    icb = icb[['Commissioner / Provider', 'Month', 'Numerator', 'Denominator']]
    df = pd.concat([df, icb], ignore_index=True)
    df[pct_col] = np.where(df['Denominator'] != 0, (df['Numerator'] / df['Denominator']) * 100, 0).round(2)
    return df[['Commissioner / Provider', 'Month', pct_col]]

def clean_national(df, pct_col):
    df = df.drop(columns=['Comparator Description', 'Age Band'], errors='ignore')
    df = df.rename(columns={'Country': 'Commissioner / Provider', 'Value': pct_col})
    df['Month'] = pd.to_datetime(df['Month'], format='%b-%y', errors='coerce')
    df['Commissioner / Provider'] = df['Commissioner / Provider'].replace(organisation_legend_mapping)
    return df[['Commissioner / Provider', 'Month', pct_col]]

if (len(local_files) == len(local_labels)) and (len(national_files) == len(national_labels)):
    all_metrics = {}

    # process locals
    for file, label in zip(local_files, local_labels):
        df = pd.read_csv(file)
        cleaned = clean_local(df, label)
        all_metrics.setdefault(label, []).append(cleaned)

    # process nationals
    for file, label in zip(national_files, national_labels):
        df = pd.read_csv(file)
        cleaned = clean_national(df, label)
        all_metrics.setdefault(label, []).append(cleaned)

    # Merge each metric set
    merged_dfs = []
    for label, df_list in all_metrics.items():
        full_df = pd.concat(df_list, ignore_index=True)
        merged = full_df.groupby(['Commissioner / Provider', 'Month'], as_index=False).first()
        merged_dfs.append(merged)

    # Final merge and pivot
    if merged_dfs:
        combined = reduce(lambda l, r: pd.merge(l, r, on=['Commissioner / Provider', 'Month'], how='outer'), merged_dfs)
    else:
        st.error("⚠️ No valid datasets were uploaded yet...")
        st.stop()

    combined = combined.sort_values(by=['Month', 'Commissioner / Provider'])

    # Create pivot tables
    pivots = {}
    for col in [c for c in combined.columns if c not in ['Commissioner / Provider', 'Month']]:
        pivot = combined.pivot_table(index='Month', columns='Commissioner / Provider', values=col).reset_index()
        pivot['Month'] = pivot['Month'].dt.strftime('%b-%y')
        pivots[col] = pivot

    # Write to Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet, df in pivots.items():
            df.to_excel(writer, sheet_name=sheet[:31], index=False)
    output.seek(0)

    st.success("✅ Processing complete!")
    st.download_button("📥 Download Excel File", data=output, file_name="overprescribing_charts.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")