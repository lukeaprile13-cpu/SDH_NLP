"""
Reading the GEMINI SDH extraction and writing outputs.
"""
import sys
import warnings
from pathlib import Path

import pandas as pd

import sdh_config as cfg

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)


def load(name, columns=None):
    """'cohort' -> DATA_DIR/cohort.parquet; 'lab' -> DATA_DIR/raw/lab.parquet."""
    for path in (cfg.DATA_DIR / f"{name}.parquet", cfg.DATA_DIR / "raw" / f"{name}.parquet"):
        if path.exists():
            if columns is not None:
                import pyarrow.parquet as pq
                have = set(pq.ParquetFile(path).schema_arrow.names)
                missing = [c for c in columns if c not in have]
                if missing:
                    print(f"  {path.name}: columns not found, left blank: {', '.join(missing)}")
                columns = [c for c in columns if c in have]
            df = pd.read_parquet(path, columns=columns)
            if "genc_id" in df:
                df["genc_id"] = df["genc_id"].astype("string")
            return df
    sys.exit(f"{name}.parquet not found in {cfg.DATA_DIR} or its raw/ folder")


def to_dt(s):
    return pd.to_datetime(s, errors="coerce", format="mixed")


def hours_between(later, earlier):
    return (later - earlier).dt.total_seconds() / 3600


def to_number(s):
    """'<0.5', '1,234', '7.2 H' -> numbers."""
    s = s.astype("string").str.replace(",", "", regex=False)
    return pd.to_numeric(s.str.extract(r"(-?\d+(?:\.\d+)?)")[0], errors="coerce")


def truthy(s):
    return s.astype("string").str.strip().str.lower().isin(["true", "t", "1", "1.0", "yes", "y"])


def has_code(code_strings, prefixes):
    """code_strings: one string of codes per row ('I620,S065;W19'): any starts with a prefix."""
    alt = "|".join(prefixes)
    return code_strings.fillna("").astype(str).str.upper().str.contains(rf"(?:^|[^A-Z0-9])(?:{alt})")


def save_patient_level(df, name):
    cfg.PATIENT_DIR.mkdir(parents=True, exist_ok=True)
    path = cfg.PATIENT_DIR / name
    (df.to_csv(path, index=False) if name.endswith(".csv") else df.to_parquet(path, index=False))
    print(f"  wrote {path} ({len(df)} rows; patient level, stays on GEMINI)")


def read_patient_level(name):
    path = cfg.PATIENT_DIR / name
    if not path.exists():
        sys.exit(f"{path} not found: run the earlier step first")
    return pd.read_parquet(path)


def suppress(n):
    if pd.isna(n):
        return ""
    n = int(n)
    return f"<{cfg.SMALL_CELL}" if 0 < n < cfg.SMALL_CELL else str(n)


def save_aggregate(df, name, count_cols=()):
    """Aggregate table with counts 1-5 suppressed (safe to share outside GEMINI)."""
    cfg.AGGREGATE_DIR.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for c in count_cols:
        out[c] = out[c].map(suppress)
    out.to_csv(cfg.AGGREGATE_DIR / name, index=False)
    print(f"  wrote aggregate/{name}")
