import streamlit as st
import pandas as pd
import numpy as np
from io import StringIO

st.set_page_config(page_title="CSV Processor", layout="wide")
st.title("CSV Processor")

# --- Load data ---
uploaded = st.file_uploader("Upload CSV", type=["csv"])

if uploaded is None:
    st.info("Please upload a CSV file to begin.")
    st.stop()

@st.cache_data
def load_df(uploaded_file):
    return pd.read_csv(uploaded_file)

df = load_df(uploaded)


st.subheader("Original loaded data (sample)")
st.dataframe(df.head(), hide_index=True)

# --- Sidebar: core picks + Data cleaning + Define Rate ---
with st.sidebar:
    st.header("Core settings")

    # Month column (needed for Month splits and 'newest' denom logic)
    month_col = st.selectbox(
        "Month column",
        options=df.columns.tolist(),
        index=df.columns.tolist().index("Month") if "Month" in df.columns else 0,
    )

    numerator_col = st.selectbox(
        "Numerator column (values to sum)",
        options=df.columns.tolist(),
        index=df.columns.tolist().index("Numerator") if "Numerator" in df.columns else (0 if len(df.columns) > 0 else 0),
    )

    denom_default_index = df.columns.tolist().index("Denominator") if "Denominator" in df.columns else (1 if len(df.columns) > 1 else 0)
    denominator_col = st.selectbox(
        "Denominator column",
        options=df.columns.tolist(),
        index=denom_default_index,
        help="By default the LAST non-missing denominator per group is used; check 'Sum Denominator across groups' to sum it instead."
    )

    sum_denominator = st.checkbox(
        "Sum Denominator across groups",
        value=False,
        help="If checked, denominators are summed per group. If unchecked (default), the most recent denominator value in the group is used."
    )

    st.markdown("---")
    st.subheader("Drop columns/rows (optional)")
    st.caption("Drop columns or rows before aggregation. Cleaned preview appears after these selections.")

    # Drop columns UI
    drop_columns = st.multiselect(
        "Columns to drop",
        options=df.columns.tolist(),
        default=[]
    )

    # Drop rows UI: choose a column, then values to drop from that column
    drop_rows_col = st.selectbox(
        "Rows to drop (choose column first)",
        options=[None] + df.columns.tolist(),
        index=0
    )

    drop_row_values = []
    if drop_rows_col:
        try:
            drop_choices = sorted(df[drop_rows_col].dropna().astype(str).unique().tolist())
        except Exception:
            drop_choices = []
        drop_row_values = st.multiselect(
            f"Values in '{drop_rows_col}' to drop (rows containing any selected values will be removed)",
            options=drop_choices,
            default=[]
        )

    st.markdown("---")
    st.subheader("Split options (choose any cleaned column)")
    st.markdown("Split aggregation by any columns from the cleaned dataset (numerator/denominator are excluded).")
    # split multiselect populated later after cleaning

# --- Apply data cleaning to create df_work (cleaned dataset) ---
df_work = df.copy()

# Drop selected columns
if drop_columns:
    df_work = df_work.drop(columns=drop_columns, errors="ignore")

# Drop selected rows by values
if drop_rows_col and drop_row_values:
    df_work = df_work[~df_work[drop_rows_col].astype(str).isin(drop_row_values)].reset_index(drop=True)

st.subheader("Cleaned data preview (sample)")
st.dataframe(df_work.head(), hide_index=True)

# After cleaning, build dynamic controls that depend on the cleaned columns:
with st.sidebar:
    # exclude numerator/denominator from split options
    split_options = [c for c in df_work.columns.tolist() if c not in (numerator_col, denominator_col)]
    split_choices = st.multiselect(
        "Split aggregation by",
        options=split_options,
        default=[]
    )

    # --- Define Rate must be immediately after split_choices (as requested) ---
    st.markdown("---")
    st.subheader("Define Rate")
    rate_mode = st.radio(
        "Rate display",
        options=["Raw rate", "Percent", "Per 1000"],
        index=0,
        help="Raw rate = Numerator / Denominator. Percent multiplies by 100. Per 1000 multiplies by 1000."
    )

# --- Robust date parsing used when Month split is selected or to determine newest denominator ---
def robust_parse_dates(series):
    s = series.astype(str).str.strip()
    s = s.str.replace("\u00A0", " ", regex=False).str.replace("\u200E", "", regex=False)
    s = s.str.replace("–", "-", regex=False).str.replace(r"[T]", " ", regex=True)
    s = s.str.replace(r'(\d)(st|nd|rd|th)\b', r'\1', regex=True)
    s = s.str.replace(r"\b\d{1,2}:\d{2}(:\d{2})?\b", "", regex=True)
    s = s.str.replace(r"\b(am|pm|AM|PM)\b", "", regex=True)
    s = s.str.replace(r"\s+", " ", regex=True).str.strip()

    parsed = pd.Series(pd.NaT, index=s.index)
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y",
        "%d/%m/%y", "%d-%b-%Y", "%d %b %Y",
        "%b-%y", "%b %y", "%B %Y",
        "%Y/%m/%d", "%d.%m.%Y", "%d.%m.%y"
    ]
    for fmt in formats:
        mask = parsed.isna()
        if not mask.any():
            break
        parsed.loc[mask] = pd.to_datetime(s[mask], format=fmt, errors="coerce", dayfirst=True)
    mask = parsed.isna()
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True, infer_datetime_format=True)
    return parsed

# --- Prepare df_work (use cleaned dataset) ---
# Ensure numeric columns exist in df_work before conversion; if missing, create NaNs
if numerator_col not in df_work.columns:
    df_work[numerator_col] = pd.NA
if denominator_col not in df_work.columns:
    df_work[denominator_col] = pd.NA

df_work[numerator_col] = pd.to_numeric(df_work[numerator_col], errors="coerce")
df_work[denominator_col] = pd.to_numeric(df_work[denominator_col], errors="coerce")

# add deterministic row order and parse Month timestamps for newest selection
df_work["_RowOrder"] = np.arange(len(df_work))
df_work["_MonthTS"] = robust_parse_dates(df_work[month_col]) if month_col in df_work.columns else pd.Series([pd.NaT]*len(df_work))

# helper to pick last non-missing from a series (after sorting)
def pick_last(series):
    s = series.dropna()
    return s.iloc[-1] if len(s) else pd.NA

# --- Build grouping columns from user-selected splits (on cleaned columns) ---
groupby_cols = list(split_choices)  # simple: no collapse/aggregate feature any more

# If Month is selected among splits, create month-period for proper grouping/sorting
if month_col in split_choices and "_MonthTS" in df_work.columns:
    df_work["_MonthPeriod"] = df_work["_MonthTS"].dt.to_period("M").dt.to_timestamp()
    # replace any occurrence of the original month_col in groupby_cols with _MonthPeriod
    groupby_cols = ["_MonthPeriod" if c == month_col else c for c in groupby_cols]
    n_bad = int(df_work["_MonthTS"].isna().sum())
    if n_bad:
        st.warning(f"{n_bad} row(s) had unparsable dates in column '{month_col}' and will be excluded from month-based splits.")

# --- Prepare a sorted version for last-non-missing denominator selection (newest by Month then row order) ---
sorted_for_last = df_work.sort_values(by=["_MonthTS", "_RowOrder"], na_position="first").reset_index(drop=True)

# --- Determine multiplier for Rate display/export based on rate_mode ---
multiplier = 1.0
if rate_mode == "Raw rate":
    multiplier = 1.0
elif rate_mode == "Percent":
    multiplier = 100.0
elif rate_mode == "Per 1000":
    multiplier = 1000.0

# --- Aggregation ---
if not groupby_cols:
    total_num = df_work[numerator_col].sum()
    if sum_denominator:
        total_den = df_work[denominator_col].sum()
    else:
        s = sorted_for_last[denominator_col].dropna()
        total_den = s.iloc[-1] if len(s) > 0 else pd.NA

    st.subheader("Total (no splits selected)")
    col1, col2 = st.columns(2)
    col1.metric(label=f"Sum of {numerator_col}", value=float(total_num))
    col2.metric(label=f"{'Sum of' if sum_denominator else 'Most recent'} {denominator_col}", value=(float(total_den) if pd.notna(total_den) else "NA"))

    grouped_display = pd.DataFrame([{f"{numerator_col}_sum": total_num, (f"{denominator_col}_sum" if sum_denominator else f"{denominator_col}_val"): total_den}])
    # compute Rate automatically if denominator is present
    num_col_name = f"{numerator_col}_sum"
    den_col_sum_name = f"{denominator_col}_sum"
    den_col_val_name = f"{denominator_col}_val"
    if den_col_sum_name in grouped_display.columns:
        den_col_name = den_col_sum_name
    elif den_col_val_name in grouped_display.columns:
        den_col_name = den_col_val_name
    else:
        den_col_name = None

    if den_col_name is not None:
        # safe division: avoid divide-by-zero
        grouped_display["Rate"] = grouped_display.apply(
            lambda r: (r[num_col_name] / r[den_col_name]) if pd.notna(r[den_col_name]) and r[den_col_name] != 0 else np.nan,
            axis=1
        )
    else:
        grouped_display["Rate"] = np.nan

    # apply multiplier for display/export
    grouped_display["Rate"] = grouped_display["Rate"] * multiplier

    st.dataframe(grouped_display, hide_index=True)

else:
    # build aggregation definitions
    if sum_denominator:
        agg_dict = {numerator_col: "sum", denominator_col: "sum"}
        grouped = (
            df_work
            .dropna(subset=[c for c in groupby_cols if (c == "_MonthPeriod") or (c in df_work.columns)])
            .groupby(groupby_cols, as_index=False)
            .agg(agg_dict)
            .rename(columns={numerator_col: f"{numerator_col}_sum", denominator_col: f"{denominator_col}_sum"})
        )
        # sort by numerator sum descending for presentation
        grouped = grouped.sort_values(f"{numerator_col}_sum", ascending=False)
    else:
        # numerator summed normally; denominator: pick last non-missing from sorted_for_last grouped
        grouped_num = (
            df_work
            .dropna(subset=[c for c in groupby_cols if (c == "_MonthPeriod") or (c in df_work.columns)])
            .groupby(groupby_cols, as_index=False)[numerator_col]
            .sum()
            .rename(columns={numerator_col: f"{numerator_col}_sum"})
        )

        grouped_den = (
            sorted_for_last
            .dropna(subset=[c for c in groupby_cols if (c == "_MonthPeriod") or (c in df_work.columns)])
            .groupby(groupby_cols, as_index=False)[denominator_col]
            .agg(pick_last)
            .rename(columns={denominator_col: f"{denominator_col}_val"})
        )

        # merge numerator sums with denominator last-values
        grouped = pd.merge(grouped_num, grouped_den, on=groupby_cols, how="left")
        grouped = grouped.sort_values(f"{numerator_col}_sum", ascending=False)

    # If month is in grouped columns, convert to display Month and reorder
    if "_MonthPeriod" in grouped.columns:
        grouped = grouped.sort_values("_MonthPeriod")
        grouped["Month"] = grouped["_MonthPeriod"].dt.strftime("%b-%y")
        cols_out = []
        cols_out.append("Month")
        for c in groupby_cols:
            if c != "_MonthPeriod":
                cols_out.append(c)
        cols_out.append(f"{numerator_col}_sum")
        cols_out.append(f"{denominator_col}_sum" if sum_denominator else f"{denominator_col}_val")
        grouped_display = grouped[cols_out]
    else:
        # generic display for arbitrary split columns
        grouped_display = grouped

    # compute Rate automatically based on available denominator column
    num_col_name = f"{numerator_col}_sum"
    den_col_sum_name = f"{denominator_col}_sum"
    den_col_val_name = f"{denominator_col}_val"
    if den_col_sum_name in grouped_display.columns:
        den_col_name = den_col_sum_name
    elif den_col_val_name in grouped_display.columns:
        den_col_name = den_col_val_name
    else:
        den_col_name = None

    if den_col_name is not None:
        grouped_display["Rate"] = grouped_display.apply(
            lambda r: (r[num_col_name] / r[den_col_name]) if pd.notna(r[den_col_name]) and r[den_col_name] != 0 else np.nan,
            axis=1
        )
    else:
        grouped_display["Rate"] = np.nan

    # apply multiplier for display/export
    grouped_display["Rate"] = grouped_display["Rate"] * multiplier

    st.subheader(f"Aggregated results (split by {', '.join(split_choices)})")
    st.dataframe(grouped_display, hide_index=True)

# --- Download ---
csv_buffer = StringIO()
grouped_display.to_csv(csv_buffer, index=False)
st.download_button(
    label="Download aggregated CSV",
    data=csv_buffer.getvalue(),
    file_name="aggregated_numerator_and_denominator.csv",
    mime="text/csv",
)

st.success("Done — aggregation complete!")
