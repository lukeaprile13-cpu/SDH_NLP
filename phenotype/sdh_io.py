"""
Reading the GEMINI SDH extraction and writing outputs.
"""
import re
import sys
import warnings

import pandas as pd
import pyarrow.parquet as pq

import sdh_config as cfg

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)


def _path(name):
    for path in (cfg.DATA_DIR / f"{name}.parquet", cfg.DATA_DIR / "raw" / f"{name}.parquet"):
        if path.exists():
            return path
    sys.exit(f"{name}.parquet not found in {cfg.DATA_DIR} or its raw/ folder")


def columns_of(name):
    return pq.ParquetFile(_path(name)).schema_arrow.names


def load(name, columns=None, genc_ids=None, keep_rows=None):
    """'cohort' -> DATA_DIR/cohort.parquet; 'lab' -> DATA_DIR/raw/lab.parquet.
    genc_ids: keep only these encounters; keep_rows: a function of a batch
    returning the rows to keep (both read in batches, for the big tables)."""
    path = _path(name)
    if columns is not None:
        have = set(columns_of(name))
        missing = [c for c in columns if c not in have]
        if missing:
            print(f"  {path.name}: columns not found, left blank: {', '.join(missing)}")
        columns = [c for c in columns if c in have]
    if genc_ids is None:
        df = pd.read_parquet(path, columns=columns)
        if "genc_id" in df:
            df["genc_id"] = df["genc_id"].astype("string")
        return df
    keep = set(map(str, genc_ids))
    parts = []
    for batch in pq.ParquetFile(path).iter_batches(columns=columns, batch_size=500_000):
        b = batch.to_pandas()
        b["genc_id"] = b["genc_id"].astype("string")
        b = b[b.genc_id.isin(keep)]
        parts.append(b[keep_rows(b)] if keep_rows is not None and len(b) else b)
    return pd.concat(parts, ignore_index=True)


def report_hash(text):
    """Fingerprint of a report's text (whitespace-insensitive), so NLP results
    are only ever matched to the exact report they were made from."""
    import hashlib
    return hashlib.md5(" ".join(str(text).split()).encode("utf-8")).hexdigest()[:16]


def to_dt(s):
    """Text or date-times -> date-times. Tries the fast single-format parse first and
    falls back to per-value parsing only when that misses values."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    fast = pd.to_datetime(s, errors="coerce")
    if fast.isna().sum() > pd.Series(s).isna().sum():
        return pd.to_datetime(s, errors="coerce", format="mixed")
    return fast


def hours_between(later, earlier):
    return (later - earlier).dt.total_seconds() / 3600


def to_number(s):
    """'<0.5', '1,234', '7.2 H' -> numbers."""
    s = s.astype("string").str.replace(",", "", regex=False)
    return pd.to_numeric(s.str.extract(r"(-?\d+(?:\.\d+)?)")[0], errors="coerce")


def truthy(s):
    return s.astype("string").str.strip().str.lower().isin(["true", "t", "1", "1.0", "yes", "y"])


# ---------------------------------------------------------------------
# Outputs. Patient-level files are CSV (small enough, open anywhere on GEMINI).
# ---------------------------------------------------------------------
TEXT_COLUMNS = ("row_id", "report_id", "episode", "patient_id_hashed", "hospital_num", "discharge_disposition_raw",
                "admit_category", "gender", "surgery_hospital", "first_surgery_code", "sdh_ip_dx_types",
                "hospitals_in_episode", "episode_genc_ids", "institution_from")


def save_patient_level(df, name):
    cfg.PATIENT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cfg.PATIENT_DIR / name, index=False)
    print(f"  wrote patient_level/{name} ({len(df)} rows; stays on GEMINI)")


def read_patient_level(name, required=True):
    path = cfg.PATIENT_DIR / name
    if not path.exists():
        if required:
            sys.exit(f"{path} not found: run the earlier step first")
        return None
    header = pd.read_csv(path, nrows=0).columns
    text = {c: "string" for c in header if "genc_id" in c or c in TEXT_COLUMNS}
    df = pd.read_csv(path, dtype=text, low_memory=False)
    for c in df.columns:
        if re.search(r"date_time$|^time_zero$|_time$|^admit$|^discharge$|^performed$", c):
            df[c] = to_dt(df[c])
    return df


def suppress(n):
    if pd.isna(n):
        return ""
    n = int(n)
    return f"<{cfg.SMALL_CELL}" if 0 < n < cfg.SMALL_CELL else str(n)


def safe_pct(k, n):
    """A percentage only when neither k nor n - k is a small cell."""
    ok = lambda x: x == 0 or x >= cfg.SMALL_CELL
    return round(100 * k / n, 1) if n and ok(k) and ok(n - k) else None


def save_aggregate(df, name, count_cols=()):
    cfg.AGGREGATE_DIR.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for c in count_cols:
        out[c] = out[c].map(suppress)
    out.to_csv(cfg.AGGREGATE_DIR / name, index=False)
    print(f"  wrote aggregate/{name}")
