"""
services/file_service.py
File upload, parsing, schema inference, and data context building.

Design principle for build_data_context:
  Give Claude the richest possible view of the data so it can reason about it
  intelligently. This means:
  - All rows (up to cap)
  - Pre-computed aggregates for every numeric column
  - Pre-computed groupby breakdowns for every categorical x numeric combination
  - Clear labelling of which file each dataset came from
  - A combined/compiled view when multiple files share the same columns

  We do NOT try to infer business meaning from filenames or impose structure.
  Claude reads the data + the agent instructions together and figures out the
  right analysis. Our job is just to make sure the data is complete and clearly
  presented — including pre-computed breakdowns so Claude can answer any
  "show me X-wise analysis" question reliably.
"""
import io, json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.config import settings


UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".json"}


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def save_upload(contents: bytes, user_id: str, dataset_id: str, filename: str) -> Path:
    ext = Path(filename).suffix.lower()
    path = UPLOAD_DIR / f"{user_id}_{dataset_id}{ext}"
    path.write_bytes(contents)
    return path


def parse_file(contents: bytes, filename: str) -> pd.DataFrame:
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        return pd.read_csv(io.BytesIO(contents))
    elif ext in (".xlsx", ".xls"):
        return pd.read_excel(io.BytesIO(contents))
    elif ext == ".json":
        data = json.loads(contents)
        return pd.DataFrame(data if isinstance(data, list) else [data])
    raise ValueError(f"Unsupported file type: {ext}")


def load_dataframe(file_path: str, nrows: Optional[int] = None) -> pd.DataFrame:
    path = Path(file_path)
    ext = path.suffix.lower()
    kwargs = {"nrows": nrows} if nrows else {}
    if ext == ".csv":
        return pd.read_csv(path, **kwargs)
    elif ext in (".xlsx", ".xls"):
        return pd.read_excel(path, **kwargs)
    elif ext == ".json":
        df = pd.read_json(path)
        return df.head(nrows) if nrows else df
    raise ValueError(f"Unsupported extension: {ext}")


def build_schema(df: pd.DataFrame) -> Dict[str, dict]:
    """Infer column types and compute per-column stats."""
    schema = {}
    total = len(df)
    for col in df.columns:
        non_null = df[col].dropna()
        nulls    = int(df[col].isna().sum())
        unique   = int(non_null.nunique())
        dtype    = str(df[col].dtype)
        sample   = [str(s) for s in non_null.head(5).tolist()]

        if "int" in dtype or "float" in dtype:
            col_type = "number"
        elif "datetime" in dtype:
            col_type = "date"
        else:
            date_like = non_null.astype(str).str.match(r"\d{4}-\d{2}-\d{2}").sum()
            col_type  = "date" if date_like > len(non_null) * 0.5 else "string"

        schema[col] = {
            "type":     col_type,
            "dtype":    dtype,
            "unique":   unique,
            "nulls":    nulls,
            "null_pct": round(nulls / total * 100, 1) if total else 0.0,
            "is_key":   unique == total and nulls == 0,
            "sample":   sample[:3],
        }
    return schema


def _dataset_block(ds: dict, max_rows: int = 300) -> str:
    """
    Build the text block for a single dataset.

    Structure:
    1. File name and dimensions
    2. Column catalogue with types and sample values
    3. Pre-computed numeric totals/averages
    4. Pre-computed groupby breakdowns: every categorical x every numeric
       — this is what allows Claude to answer "rep-wise", "geography-wise",
         "customer-wise" etc. reliably without scanning raw rows
    5. Date ranges if date columns present
    6. All raw rows (up to cap)
    """
    try:
        df = load_dataframe(ds["file_path"])
    except Exception as e:
        return f'=== FILE: "{ds["name"]}" — could not load: {e} ==='

    schema    = ds.get("schema", build_schema(df))
    num_cols  = [c for c in df.columns if schema.get(c, {}).get("type") == "number"]
    cat_cols  = [
        c for c in df.columns
        if schema.get(c, {}).get("type") == "string"
        and 1 < schema.get(c, {}).get("unique", 0) < 100  # skip ID cols and free-text
    ]
    date_cols = [c for c in df.columns if schema.get(c, {}).get("type") == "date"]

    lines = []
    original_name = ds.get("filename", ds["name"])
    lines.append(
        f'=== FILE: "{original_name}" ({len(df):,} rows x {len(df.columns)} columns) ==='
    )

    # Column catalogue
    lines.append("COLUMNS:")
    for col in df.columns:
        s       = schema.get(col, {})
        ctype   = s.get("type", "?")
        nullpct = s.get("null_pct", 0)
        samp    = ", ".join(s.get("sample", []))
        null_note = f" [{nullpct}% empty]" if nullpct > 0 else ""
        lines.append(f"  {col} ({ctype}){null_note} — e.g. {samp}")

    # Numeric totals
    if num_cols:
        lines.append("\nNUMERIC TOTALS:")
        for col in num_cols:
            vals = df[col].dropna()
            if len(vals):
                lines.append(
                    f"  {col}: total={vals.sum():,.2f}  avg={vals.mean():,.2f}"
                    f"  min={vals.min():,.2f}  max={vals.max():,.2f}  count={len(vals):,}"
                )

    # Groupby breakdowns — the critical section
    # Pre-computing these means Claude can answer ANY grouping question
    # ("by rep", "by region", "by customer", "by product") directly from
    # the pre-computed table, regardless of what the column is named.
    if cat_cols and num_cols:
        lines.append(
            "\nPRE-COMPUTED GROUPBY BREAKDOWNS "
            "(use these to answer any 'X-wise' or 'by X' questions):"
        )
        for cat in cat_cols:
            for num in num_cols:
                try:
                    grp = (
                        df.groupby(cat)[num]
                        .sum()
                        .sort_values(ascending=False)
                        .head(30)
                    )
                    if len(grp) == 0:
                        continue
                    entries = "  |  ".join(f"{k}: {v:,.2f}" for k, v in grp.items())
                    lines.append(f"  {cat} vs {num}: {entries}")
                except Exception:
                    pass

    # Date ranges
    if date_cols:
        lines.append("\nDATE RANGES:")
        for col in date_cols:
            try:
                parsed = pd.to_datetime(df[col], errors="coerce").dropna()
                if len(parsed):
                    lines.append(
                        f"  {col}: {parsed.min().date()} to {parsed.max().date()}"
                    )
            except Exception:
                pass

    # Raw rows
    cap = min(len(df), max_rows)
    header = " | ".join(str(c) for c in df.columns)
    rows_txt = "\n".join(
        " | ".join("" if pd.isna(v) else str(v) for v in row)
        for row in df.head(cap).itertuples(index=False, name=None)
    )
    trunc = f"\n[Showing first {cap} of {len(df):,} rows]" if len(df) > cap else ""
    lines.append(f"\nALL ROWS:\n{header}\n{rows_txt}{trunc}")

    return "\n".join(lines)


def _cross_file_block(datasets: List[dict]) -> str:
    """
    When multiple files are uploaded, stack them and produce cross-file totals.
    Labels each row with its source filename so Claude can attribute data correctly.

    Only produced when 2+ files share at least one numeric column.
    Makes no assumptions about what the files mean — pure data combination.
    """
    dfs = []
    for ds in datasets:
        try:
            df = load_dataframe(ds["file_path"])
            df["__file__"] = ds.get("filename", ds["name"])
            dfs.append(df)
        except Exception:
            pass

    if len(dfs) < 2:
        return ""

    try:
        combined = pd.concat(dfs, ignore_index=True)
    except Exception:
        return ""

    num_cols = [
        c for c in combined.select_dtypes(include="number").columns
        if c != "__file__"
    ]
    if not num_cols:
        return ""

    file_names = [ds.get("filename", ds["name"]) for ds in datasets]
    lines = [
        "\n=== COMBINED VIEW — ALL FILES MERGED ===",
        f"Files: {', '.join(file_names)}",
        f"Total rows combined: {len(combined):,}",
        "\nCOMBINED TOTALS:",
    ]

    for col in num_cols:
        vals = combined[col].dropna()
        if len(vals):
            lines.append(
                f"  {col}: grand total={vals.sum():,.2f}  avg={vals.mean():,.2f}"
                f"  min={vals.min():,.2f}  max={vals.max():,.2f}"
            )

    # Totals broken down by source file
    lines.append("\nBY SOURCE FILE:")
    for col in num_cols:
        try:
            grp = (
                combined.groupby("__file__")[col]
                .sum()
                .sort_values(ascending=False)
            )
            entries = "  |  ".join(f"{k}: {v:,.2f}" for k, v in grp.items())
            lines.append(f"  {col} per file: {entries}")
        except Exception:
            pass

    # Cross-file groupby breakdowns for shared categorical columns
    cat_cols = [
        c for c in combined.columns
        if c != "__file__"
        and combined[c].dtype == object
        and 1 < combined[c].nunique() < 100
    ]
    if cat_cols:
        lines.append("\nCOMBINED BREAKDOWNS (across all files):")
        for cat in cat_cols:
            for num in num_cols:
                try:
                    grp = (
                        combined.groupby(cat)[num]
                        .sum()
                        .sort_values(ascending=False)
                        .head(30)
                    )
                    if len(grp) == 0:
                        continue
                    entries = "  |  ".join(f"{k}: {v:,.2f}" for k, v in grp.items())
                    lines.append(f"  {cat} vs {num} (all files): {entries}")
                except Exception:
                    pass

    return "\n".join(lines)


def build_data_context(datasets: List[dict], user_id: str, max_rows: int = 300) -> str:
    """
    Build the full data context string injected into every Claude call.

    The pre-computed groupby breakdowns are the key architectural decision here.
    Instead of giving Claude raw rows and asking it to group mentally,
    we hand it every categorical x numeric breakdown pre-computed.
    This means Claude can reliably answer "rep-wise", "geography-wise",
    "customer-wise", "product-wise" — or any other grouping — regardless
    of what the column happens to be named in the user's actual file.
    """
    if not datasets:
        return ""

    parts = [_dataset_block(ds, max_rows) for ds in datasets]

    if len(datasets) > 1:
        cross = _cross_file_block(datasets)
        if cross:
            parts.append(cross)

    context = "\n\n".join(p for p in parts if p)

    return (
        f"\n\n{context}\n\n"
        "DATA USAGE NOTES:\n"
        "- All data above is complete. Use it directly.\n"
        "- The PRE-COMPUTED GROUPBY BREAKDOWNS sections contain grouped totals "
        "for every combination of categorical and numeric column. "
        "Use these to answer any question about performance by person, region, "
        "customer, product, or any other dimension — the grouping is already done.\n"
        "- If multiple files are present, the COMBINED VIEW section has cross-file totals.\n"
        "- Never ask the user for more data. Never say a calculation is not possible."
    )


def numeric_summary(file_path: str) -> dict:
    """Quick numeric summary for the /agent/run endpoint."""
    df = load_dataframe(file_path)
    num_cols = df.select_dtypes(include="number").columns.tolist()
    summary = {}
    for col in num_cols[:15]:
        vals = df[col].dropna()
        summary[col] = {
            "sum":   float(vals.sum()),
            "mean":  float(vals.mean()),
            "min":   float(vals.min()),
            "max":   float(vals.max()),
            "nulls": int(df[col].isna().sum()),
        }
    return {
        "name":            Path(file_path).stem,
        "rows":            len(df),
        "columns":         list(df.columns),
        "numeric_summary": summary,
        "sample_rows":     df.head(5).where(pd.notna(df.head(5)), None).to_dict(orient="records"),
    }
