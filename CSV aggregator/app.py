import streamlit as st
import pandas as pd
import numpy as np
from io import StringIO

st.set_page_config(page_title="CSV Processor", layout="wide")
st.title("CSV Processor")

# ---------------------------
# Session state initialization
# ---------------------------
st.session_state.setdefault("queue", [])
st.session_state.setdefault("queued_rate_label_input", "")
st.session_state.setdefault("merge_keys_select", [])
st.session_state.setdefault("drop_numden_on_merge", False)

# ---------------------------
# Helper: normalize merge key column values (strings)
# ---------------------------
def normalize_key_series(s: pd.Series) -> pd.Series:
    if not pd.api.types.is_object_dtype(s) and not pd.api.types.is_string_dtype(s):
        return s
    s2 = s.astype(str)
    s2 = s2.str.replace("\u00A0", " ", regex=False)
    s2 = s2.str.replace("\u200E", "", regex=False)
    s2 = s2.str.replace("–", "-", regex=False)
    s2 = s2.str.replace("—", "-", regex=False)
    s2 = s2.str.replace("\u2013", "-", regex=False)
    s2 = s2.str.replace("\u2014", "-", regex=False)
    s2 = s2.str.replace(r"\s+", " ", regex=True)
    s2 = s2.str.strip()
    s2 = s2.replace({"nan": np.nan, "None": np.nan})
    return s2

# ---------------------------
# Load data
# ---------------------------
uploaded = st.file_uploader("Upload CSV", type=["csv"])
if uploaded is None:
    st.info("Please upload a CSV file to begin.")
    st.stop()

@st.cache_data
def load_df(uploaded_file):
    return pd.read_csv(uploaded_file)

df = load_df(uploaded)
st.subheader("Original loaded data")
st.dataframe(df.head(), hide_index=True)

# ---------------------------
# Sidebar: core settings
# ---------------------------
with st.sidebar:
    st.header("Core settings")

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

    drop_columns = st.multiselect(
        "Columns to drop",
        options=df.columns.tolist(),
        default=[]
    )

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
    st.subheader("Split options")
    # split_choices widget populated after cleaning below

# ---------------------------
# Data cleaning -> df_work
# ---------------------------
df_work = df.copy()
if drop_columns:
    df_work = df_work.drop(columns=drop_columns, errors="ignore")
if drop_rows_col and drop_row_values:
    df_work = df_work[~df_work[drop_rows_col].astype(str).isin(drop_row_values)].reset_index(drop=True)

st.subheader("Cleaned data")
st.dataframe(df_work.head(), hide_index=True)

# ---------------------------
# Sidebar (after cleaning): split choices, rate mode, queue UI
# ---------------------------
with st.sidebar:
    split_options = [c for c in df_work.columns.tolist() if c not in (numerator_col, denominator_col)]
    split_choices = st.multiselect(
        "Split aggregation by",
        options=split_options,
        default=[]
    )

    st.markdown("---")
    st.subheader("Define Rate")
    rate_mode = st.radio(
        "Rate display",
        options=["Raw rate", "Percent", "Per 1000"],
        index=0,
        help="Raw rate = Numerator / Denominator. Percent multiplies by 100. Per 1000 multiplies by 1000."
    )

    st.markdown("---")
    st.subheader("Queue aggregated CSVs")

    queued_rate_label = st.text_input(
        "Rate label for this CSV",
        value=st.session_state["queued_rate_label_input"],
        key="queued_rate_label_input"
    )

    add_to_queue_btn = st.button("Add current CSV to queue", key="add_to_queue")

    st.markdown("---")
    st.subheader("Queued items")
    if st.session_state["queue"]:
        for i in range(len(st.session_state["queue"])):
            item = st.session_state["queue"][i]
            c1, c2 = st.columns([6, 1])
            with c1:
                new_rate_label = st.text_input(f"Rate label {i+1}", value=item.get("rate_label", ""), key=f"qlabel_{i}")
                st.session_state["queue"][i]["rate_label"] = new_rate_label
            with c2:
                if st.button("✕", key=f"remove_{i}"):
                    st.session_state["queue"].pop(i)
                    st.rerun()
    else:
        st.info("Queue is empty — add an aggregated result to begin.")

    st.markdown("---")
    st.subheader("Merge queued items")

    def candidate_common_columns(queue):
        if not queue:
            return []
        dfs = [item["df"].copy() for item in queue]
        common_cols = set(dfs[0].columns)
        for d in dfs[1:]:
            common_cols &= set(d.columns)
        filtered = []
        for c in sorted(common_cols):
            cl = c.lower()
            if cl.endswith(("_sum", "_val")):
                continue
            if "rate" in cl:
                continue
            filtered.append(c)
        if "Month" in filtered:
            filtered.remove("Month")
            filtered = ["Month"] + filtered
        return filtered

    merge_candidates = candidate_common_columns(st.session_state["queue"])
    if merge_candidates:
        default_keys = ["Month"] if "Month" in merge_candidates else [merge_candidates[0]]
    else:
        default_keys = []

    merge_keys = st.multiselect(
        "Select columns that should match between CSVs (rows with the same values will be combined)",
        options=merge_candidates,
        default=st.session_state.get("merge_keys_select", default_keys),
        key="merge_keys_select"
    )

    # NEW: checkbox to drop numerator/denominator columns from merged output
    drop_numden_on_merge = st.checkbox(
        "Drop numerator and denominator columns from merged output",
        value=st.session_state.get("drop_numden_on_merge", False),
        key="drop_numden_on_merge"
    )

    # Only outer merge now
    merge_btn = st.button("Create merged output from queue", key="merge_queue")

    if st.session_state["queue"]:
        if st.button("Clear entire queue", key="clear_queue"):
            st.session_state["queue"] = []
            st.rerun()

# ---------------------------
# Robust date parsing helper
# ---------------------------
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

# ---------------------------
# Prepare df_work (numeric parsing, month TS, etc.)
# ---------------------------
if numerator_col not in df_work.columns:
    df_work[numerator_col] = pd.NA
if denominator_col not in df_work.columns:
    df_work[denominator_col] = pd.NA

df_work[numerator_col] = pd.to_numeric(df_work[numerator_col], errors="coerce")
df_work[denominator_col] = pd.to_numeric(df_work[denominator_col], errors="coerce")

df_work["_RowOrder"] = np.arange(len(df_work))
df_work["_MonthTS"] = robust_parse_dates(df_work[month_col]) if month_col in df_work.columns else pd.Series([pd.NaT]*len(df_work))

def pick_last(series):
    s = series.dropna()
    return s.iloc[-1] if len(s) else pd.NA

groupby_cols = list(split_choices)
if month_col in split_choices and "_MonthTS" in df_work.columns:
    df_work["_MonthPeriod"] = df_work["_MonthTS"].dt.to_period("M").dt.to_timestamp()
    groupby_cols = ["_MonthPeriod" if c == month_col else c for c in groupby_cols]
    n_bad = int(df_work["_MonthTS"].isna().sum())
    if n_bad:
        st.warning(f"{n_bad} row(s) had unparsable dates in column '{month_col}' and will be excluded from month-based splits.")

sorted_for_last = df_work.sort_values(by=["_MonthTS", "_RowOrder"], na_position="first").reset_index(drop=True)

multiplier = 1.0
if rate_mode == "Raw rate":
    multiplier = 1.0
elif rate_mode == "Percent":
    multiplier = 100.0
elif rate_mode == "Per 1000":
    multiplier = 1000.0

# ---------------------------
# Aggregation logic (produces grouped_display)
# ---------------------------
grouped_display = None

if not groupby_cols:
    total_num = df_work[numerator_col].sum()
    if sum_denominator:
        total_den = df_work[denominator_col].sum()
    else:
        s = sorted_for_last[denominator_col].dropna()
        total_den = s.iloc[-1] if len(s) > 0 else pd.NA

    st.subheader("Aggregated data (no splits selected)")
    col1, col2 = st.columns(2)
    col1.metric(label=f"Sum of {numerator_col}", value=float(total_num))
    col2.metric(label=f"{'Sum of' if sum_denominator else 'Most recent'} {denominator_col}", value=(float(total_den) if pd.notna(total_den) else "NA"))

    grouped_display = pd.DataFrame([{f"{numerator_col}_sum": total_num, (f"{denominator_col}_sum" if sum_denominator else f"{denominator_col}_val"): total_den}])

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

    grouped_display["Rate"] = grouped_display["Rate"] * multiplier

    st.dataframe(grouped_display, hide_index=True)
else:
    if sum_denominator:
        agg_dict = {numerator_col: "sum", denominator_col: "sum"}
        grouped = (
            df_work
            .dropna(subset=[c for c in groupby_cols if (c == "_MonthPeriod") or (c in df_work.columns)])
            .groupby(groupby_cols, as_index=False)
            .agg(agg_dict)
            .rename(columns={numerator_col: f"{numerator_col}_sum", denominator_col: f"{denominator_col}_sum"})
        )
        grouped = grouped.sort_values(f"{numerator_col}_sum", ascending=False)
    else:
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

        grouped = pd.merge(grouped_num, grouped_den, on=groupby_cols, how="left")
        grouped = grouped.sort_values(f"{numerator_col}_sum", ascending=False)

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
        grouped_display = grouped

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

    grouped_display["Rate"] = grouped_display["Rate"] * multiplier

    st.subheader(f"Aggregated results (split by {', '.join(split_choices)})")
    st.dataframe(grouped_display, hide_index=True)

# ---------------------------
# Download single aggregated CSV
# ---------------------------
if grouped_display is not None:
    csv_buffer = StringIO()
    grouped_display.to_csv(csv_buffer, index=False)
    st.download_button(
        label="Download aggregated CSV",
        data=csv_buffer.getvalue(),
        file_name="aggregated_numerator_and_denominator.csv",
        mime="text/csv",
    )
else:
    st.info("No aggregated data to download. Adjust splits / inputs to produce aggregation.")

# ---------------------------
# Queue: add current aggregated result (rate label used as identifier)
# ---------------------------
def _make_default_label():
    return f"queued_{len(st.session_state['queue'])+1}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}"

if add_to_queue_btn:
    if grouped_display is None:
        st.warning("No aggregated output to add to the queue. Perform an aggregation first.")
    else:
        df_to_queue = grouped_display.copy()
        label = st.session_state.get("queued_rate_label_input", "").strip()
        stored_rate_label = ""
        if "Rate" in df_to_queue.columns and label:
            candidate = label
            k = 1
            while candidate in df_to_queue.columns or any(item["rate_label"] == candidate for item in st.session_state["queue"]):
                candidate = f"{label}_{k}"
                k += 1
            df_to_queue = df_to_queue.rename(columns={"Rate": candidate})
            stored_rate_label = candidate
        else:
            stored_rate_label = "Rate" if "Rate" in df_to_queue.columns else _make_default_label()
        st.session_state["queue"].append({"rate_label": stored_rate_label, "df": df_to_queue})
        st.rerun()

# ---------------------------
# NEW: Robust month parsing function used by sorting
# ---------------------------
def _parse_month_like(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    fmts = [
        "%b-%y", "%b-%Y", "%B-%y", "%B-%Y",
        "%Y-%m-%d", "%Y-%m", "%Y/%m", "%m/%Y", "%m-%Y",
        "%b %y", "%b %Y", "%B %Y", "%b.%y", "%b.%Y"
    ]
    for fmt in fmts:
        try:
            parsed = pd.to_datetime(s, format=fmt, errors="coerce")
            if parsed.notna().any():
                return parsed
        except Exception:
            continue
    try:
        parsed2 = robust_parse_dates(series)
        if parsed2.notna().any():
            return parsed2
    except Exception:
        pass
    try:
        parsed3 = pd.to_datetime(series, errors="coerce", infer_datetime_format=True, dayfirst=False)
        return parsed3
    except Exception:
        return pd.Series([pd.NaT] * len(series), index=series.index)

def _try_sort_by_month(df, tie_keys=None):
    if "_MonthPeriod" in df.columns:
        try:
            if tie_keys:
                return df.sort_values(["_MonthPeriod"] + tie_keys).reset_index(drop=True)
            return df.sort_values("_MonthPeriod").reset_index(drop=True)
        except Exception:
            pass
    if "Month" in df.columns:
        parsed = _parse_month_like(df["Month"])
        if parsed.notna().any():
            df["_SortMonth"] = parsed
            if tie_keys:
                df = df.sort_values(["_SortMonth"] + (tie_keys if tie_keys else [])).reset_index(drop=True)
            else:
                df = df.sort_values("_SortMonth").reset_index(drop=True)
            df = df.drop(columns=["_SortMonth"])
            return df
    month_like = [c for c in df.columns if "month" in c.lower() and c not in ("_MonthPeriod", "Month")]
    for col in month_like:
        parsed = _parse_month_like(df[col])
        if parsed.notna().any():
            df["_SortMonth"] = parsed
            if tie_keys:
                df = df.sort_values(["_SortMonth"] + (tie_keys if tie_keys else [])).reset_index(drop=True)
            else:
                df = df.sort_values("_SortMonth").reset_index(drop=True)
            df = df.drop(columns=["_SortMonth"])
            return df
    return df

# ---------------------------
# Merge queued items (outer merge on chosen keys + normalization + coalescing)
# ---------------------------
merged_result = None
if merge_btn:
    queue = st.session_state["queue"]
    if not queue:
        st.warning("Queue is empty — nothing to merge.")
    elif len(queue) == 1:
        st.info("Only one item in queue — merging returns that single item.")
        merged_result = queue[0]["df"].copy()
    else:
        dfs = [item["df"].copy() for item in queue]

        # chosen keys verification and fallback to Month if possible
        chosen_keys = st.session_state.get("merge_keys_select", []) or []
        chosen_keys = [k for k in chosen_keys if all(k in d.columns for d in dfs)]
        if not chosen_keys and all("Month" in d.columns for d in dfs):
            chosen_keys = ["Month"]

        # normalize chosen key columns across dfs
        for k in chosen_keys:
            for i, d in enumerate(dfs):
                if k in d.columns:
                    try:
                        dfs[i][k] = normalize_key_series(dfs[i][k])
                    except Exception:
                        pass

        if not chosen_keys:
            st.warning("No merge keys selected or detected; falling back to concatenation (no coalescing).")
            try:
                merged_result = pd.concat(dfs, ignore_index=True, sort=False)
            except Exception as e:
                st.error(f"Concatenation failed: {e}")
                merged_result = None
        else:
            merged_result = dfs[0]
            for d in dfs[1:]:
                try:
                    merged_result = pd.merge(merged_result, d, on=chosen_keys, how="outer", suffixes=("", "_r"))
                except Exception as e:
                    st.error(f"Merge failed part-way: {e}")
                    merged_result = None
                    break
            if merged_result is not None:
                for col in list(merged_result.columns):
                    if col.endswith("_r"):
                        base = col[:-2]
                        if base in merged_result.columns:
                            merged_result[base] = merged_result[base].combine_first(merged_result[col])
                            merged_result = merged_result.drop(columns=[col])

        # --- SORT merged_result by month (oldest -> newest) when possible, tie-break by chosen_keys
        if merged_result is not None:
            try:
                merged_result = _try_sort_by_month(merged_result, tie_keys=chosen_keys if chosen_keys else None)
            except Exception:
                pass

    # BEFORE preview/download: optionally drop numerator/denominator columns if user asked
    merged_for_output = None
    if merged_result is not None:
        if st.session_state.get("drop_numden_on_merge", False):
            # candidate names to drop
            drop_candidates = []
            drop_candidates.append(f"{numerator_col}_sum")
            drop_candidates.append(f"{denominator_col}_sum")
            drop_candidates.append(f"{denominator_col}_val")
            # also drop the raw names if present
            drop_candidates.append(numerator_col)
            drop_candidates.append(denominator_col)
            # drop any that exist
            merged_for_output = merged_result.drop(columns=[c for c in drop_candidates if c in merged_result.columns], errors="ignore")
        else:
            merged_for_output = merged_result.copy()

    # show merged preview and download
    if merged_for_output is not None:
        st.subheader("Merged output (from queue)")
        st.dataframe(merged_for_output.head(50), hide_index=True)

        mbuf = StringIO()
        merged_for_output.to_csv(mbuf, index=False)
        st.download_button(
            label="Download merged CSV",
            data=mbuf.getvalue(),
            file_name="merged_queued_outputs.csv",
            mime="text/csv",
        )
        st.success("Merged output ready.")