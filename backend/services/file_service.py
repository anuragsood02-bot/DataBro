"""
services/file_service.py
File upload, parsing, schema inference, data context building.
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
    """Infer column types and compute metadata stats."""
    schema = {}
    total = len(df)
    for col in df.columns:
        non_null = df[col].dropna()
        nulls = int(df[col].isna().sum())
        unique = int(non_null.nunique())
        dtype = str(df[col].dtype)
        sample = [str(s) for s in non_null.head(5).tolist()]

        if "int" in dtype or "float" in dtype:
            col_type = "number"
        elif "datetime" in dtype:
            col_type = "date"
        else:
            date_like = non_null.astype(str).str.match(r"\d{4}-\d{2}-\d{2}").sum()
            col_type = "date" if date_like > len(non_null) * 0.5 else "string"

        schema[col] = {
            "type": col_type,
            "dtype": dtype,
            "unique": unique,
            "nulls": nulls,
            "null_pct": round(nulls / total * 100, 1) if total else 0.0,
            "is_key": unique == total and nulls == 0,
            "sample": sample[:3],
        }
    return schema


def build_data_context(datasets: List[dict], user_id: str, max_rows: int = 300) -> str:
    """
    Build a rich data context string to inject into Claude's system prompt.
    Includes all rows (up to max_rows), computed aggregates, and categorical breakdowns.
    """
    if not datasets:
        return ""

    parts = []
    for ds in datasets:
        try:
            df = load_dataframe(ds["file_path"])
        except Exception as e:
            parts.append(f'Dataset "{ds["name"]}": could not load — {e}')
            continue

        schema = ds.get("schema", build_schema(df))
        num_cols = [f for f in df.columns if schema.get(f, {}).get("type") == "number"]
        str_cols = [f for f in df.columns if schema.get(f, {}).get("type") == "string"
                    and schema.get(f, {}).get("unique", 999) < 60]

        # Column info
        col_info = "\n".join(
            f"  - {f} ({schema.get(f,{}).get('type','?')})"
            + (" [KEY]" if schema.get(f, {}).get("is_key") else "")
            + (f" [{schema.get(f,{}).get('null_pct',0)}% nulls]" if schema.get(f, {}).get("null_pct", 0) > 0 else "")
            for f in df.columns
        )

        # Numeric aggregates
        aggs = ""
        if num_cols:
            agg_lines = []
            for f in num_cols:
                vals = df[f].dropna()
                if len(vals):
                    agg_lines.append(
                        f"  {f}: sum={vals.sum():,.0f} | avg={vals.mean():.1f} | min={vals.min()} | max={vals.max()}"
                    )
            if agg_lines:
                aggs = "\nNumeric column summaries:\n" + "\n".join(agg_lines)

        # Categorical breakdowns
        cats = ""
        if str_cols and num_cols:
            nf = num_cols[0]
            cat_lines = []
            for sf in str_cols[:3]:
                grouped = df.groupby(sf)[nf].sum().sort_values(ascending=False).head(10)
                entries = ", ".join(f"{k}={v:,.0f}" for k, v in grouped.items())
                cat_lines.append(f"  By {sf}: {entries}")
            if cat_lines:
                cats = f"\nTop values by {nf}:\n" + "\n".join(cat_lines)

        # All rows as CSV text
        cap = min(len(df), max_rows)
        header = " | ".join(df.columns)
        rows_txt = "\n".join(
            " | ".join(str(r.get(c, "")) for c in df.columns)
            for r in df.head(cap).to_dict(orient="records")
        )
        trunc = f"\n(showing first {cap} of {len(df)} rows)" if len(df) > cap else ""

        parts.append(
            f'=== Dataset: "{ds["name"]}" ({len(df)} rows × {len(df.columns)} cols) ===\n'
            f"Columns:\n{col_info}"
            f"{aggs}{cats}\n"
            f"Full data:\n{header}\n{rows_txt}{trunc}"
        )

    context = "\n\n".join(parts)
    return (
        f"\n\n{context}\n\n"
        "IMPORTANT: You have full access to ALL the data above. "
        "Answer questions directly using this data — do NOT ask the user to provide data or copy-paste rows."
    )


def numeric_summary(file_path: str) -> dict:
    """Quick numeric summary for agent/run endpoint."""
    df = load_dataframe(file_path)
    num_cols = df.select_dtypes(include="number").columns.tolist()
    summary = {}
    for col in num_cols[:15]:
        vals = df[col].dropna()
        summary[col] = {
            "sum": float(vals.sum()),
            "mean": float(vals.mean()),
            "min": float(vals.min()),
            "max": float(vals.max()),
            "nulls": int(df[col].isna().sum()),
        }
    return {
        "name": Path(file_path).stem,
        "rows": len(df),
        "columns": list(df.columns),
        "numeric_summary": summary,
        "sample_rows": df.head(5).where(pd.notna(df.head(5)), None).to_dict(orient="records"),
    }
