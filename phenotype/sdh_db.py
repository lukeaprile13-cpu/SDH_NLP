"""
Database and file helpers shared by the cohort scripts.

The session is read-only: nothing is ever written to the database (no temp
tables either), so lists of encounters are passed as query parameters.
"""
import os
import re
import sys
import warnings
from pathlib import Path

import pandas as pd

import sdh_config as cfg

try:
    import psycopg2
except ImportError:
    sys.exit("psycopg2 is not installed: pip install psycopg2-binary")

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

CHUNK = 5000
ID_COLUMNS = ("genc_id", "patient_id_hashed", "hospital_num")
GENC_ID_IS_INTEGER = True        # set from the schema by Schema()


# ---------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------
def _credentials():
    env = {k: os.environ.get(f"SDH_DB_{k.upper()}") for k in ("dbname", "host", "user", "password")}
    if all(env.values()):
        return env
    path = Path(cfg.CREDENTIALS_R_FILE)
    if not path.exists():
        sys.exit(f"Connection file {path} not found: run from the project folder, or set "
                 "SDH_CREDENTIALS_FILE / the SDH_DB_* environment variables.")
    source = path.read_text()
    creds = {}
    for name in ("dbname", "host", "user", "password"):
        m = re.search(r"\b" + name + r'\s*=\s*"([^"]+)"', source)
        if not m and not env[name]:
            sys.exit(f"Missing connection setting '{name}' in {path}")
        creds[name] = env[name] or m.group(1)
    return creds


def connect():
    conn = psycopg2.connect(**_credentials(), port=cfg.DB_PORT, connect_timeout=15)
    conn.set_session(readonly=True, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = %s", (cfg.STATEMENT_TIMEOUT,))
        cur.execute(f"SET search_path TO {cfg.SCHEMA}, public")
        cur.execute("SELECT current_database(), current_schema(), "
                    "current_setting('transaction_read_only')")
        db, schema, ro = cur.fetchone()
    print(f"Connected: database {db}, schema {schema}, read-only {ro}")
    return conn


def query(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    # identifiers are kept as text in Python so files and queries always join
    for c in ID_COLUMNS:
        if c in df.columns:
            df[c] = df[c].map(lambda v: None if pd.isna(v) or str(v).strip() == "" else str(v).strip()).astype("string")
    return df


def query_ids(conn, sql, ids, kind="genc", params=None):
    """Run `sql` (holding `= ANY(%(ids)s)`) in chunks. kind: "genc" or "text".
    `params`: any other named parameters the query uses."""
    ids = pd.unique(pd.Series(list(ids), dtype="string").dropna())
    if kind == "genc" and GENC_ID_IS_INTEGER:
        ids = [int(i) for i in ids]
    else:
        ids = [str(i) for i in ids]
    id_param = "ids"
    params = dict(params or {})
    parts = [query(conn, sql, {**params, id_param: ids[i:i + CHUNK]}) for i in range(0, len(ids), CHUNK)]
    if not parts:
        return query(conn, sql, {**params, id_param: []})
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------
# Tables and columns (names differ between GEMINI data cuts)
# ---------------------------------------------------------------------
class Schema:
    def __init__(self, conn):
        cols = query(conn, """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position""", (cfg.SCHEMA,))
        self.columns = {t: list(g.column_name) for t, g in cols.groupby("table_name")}
        self.types = {(r.table_name, r.column_name): r.data_type for r in cols.itertuples()}
        global GENC_ID_IS_INTEGER
        admdad = self.table("admdad")
        GENC_ID_IS_INTEGER = self.types.get((admdad, "genc_id"), "integer") in (
            "integer", "bigint", "smallint", "numeric")

    def table(self, name, required=True):
        """'admdad' -> 'admdad_subset' (or None if it is not in this data cut)."""
        for candidate in (name + cfg.TABLE_SUFFIX, name):
            if candidate in self.columns:
                return candidate
        if required:
            sys.exit(f"Table {name}{cfg.TABLE_SUFFIX} not found in schema {cfg.SCHEMA}. "
                     f"Tables: {', '.join(sorted(self.columns))}")
        return None

    def find_tables(self, pattern):
        return [t for t in self.columns if re.search(pattern, t)]

    def col(self, table, patterns, required=False):
        """First column of `table` matching one of the regex patterns, in order."""
        if table is None:
            return None
        for p in ([patterns] if isinstance(patterns, str) else patterns):
            for c in self.columns.get(table, []):
                if re.search(p, c):
                    return c
        if required:
            sys.exit(f"No column like {patterns} in {table}: {', '.join(self.columns[table])}")
        return None

    def cols(self, table, pattern):
        return [c for c in self.columns.get(table, []) if re.search(pattern, c)]


# ---------------------------------------------------------------------
# Date-times
# ---------------------------------------------------------------------
def to_dt(series):
    return pd.to_datetime(series, errors="coerce", format="mixed")


def combine_date_time(date_s, time_s=None):
    """A date column plus an optional time column ('0930', '09:30', '09:30:00')."""
    d = to_dt(date_s).dt.normalize()
    if time_s is None:
        return d, pd.Series(False, index=d.index)
    t = time_s.astype("string").str.replace(r"[^0-9]", "", regex=True).str.zfill(4).str[:4]
    ok = t.str.fullmatch(r"([01]\d|2[0-3])[0-5]\d").fillna(False).astype(bool)
    hours = pd.to_numeric(t.str[:2], errors="coerce")
    mins = pd.to_numeric(t.str[2:4], errors="coerce")
    out = d + pd.to_timedelta(hours.where(ok, 0), unit="h") + pd.to_timedelta(mins.where(ok, 0), unit="m")
    return out, ok


def hours_between(later, earlier):
    return (later - earlier).dt.total_seconds() / 3600


def to_number(series):
    """'<0.5', '1,234', '7.2 H' -> numbers (comparators dropped)."""
    s = series.astype("string").str.replace(",", "", regex=False)
    return pd.to_numeric(s.str.extract(r"(-?\d+(?:\.\d+)?)")[0], errors="coerce")


# ---------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------
def ensure_dirs():
    cfg.PATIENT_DIR.mkdir(parents=True, exist_ok=True)
    cfg.AGGREGATE_DIR.mkdir(parents=True, exist_ok=True)


def save_patient_level(df, name):
    ensure_dirs()
    path = cfg.PATIENT_DIR / name
    df.to_csv(path, index=False)
    print(f"  wrote {path} ({len(df)} rows) - patient level: keep on the server")
    return path


def read_patient_level(name):
    path = cfg.PATIENT_DIR / name
    if not path.exists():
        sys.exit(f"{path} not found: run the earlier step first")
    header = pd.read_csv(path, nrows=0).columns
    text = ("row_id", "discharge_disposition", "discharge_disposition_raw", "admit_category", "gender",
            "institution_from", "institution_from_type", "admit_via_ambulance", "sdh_types", "sdh_codes",
            "surgery_hospital", "first_surgery_code")
    ids = {c: "string" for c in header if "genc_id" in c or c in ID_COLUMNS or c in text}
    return pd.read_csv(path, low_memory=False, dtype=ids)


def pg_regex(pattern):
    """Python regex -> PostgreSQL regex (word boundary is \\y there; \\b is backspace)."""
    return pattern.replace(r"\b", r"\y")


def suppress(n):
    """Cell suppression: 1-5 -> '<6'."""
    if pd.isna(n):
        return ""
    n = int(n)
    return f"<{cfg.SMALL_CELL}" if 0 < n < cfg.SMALL_CELL else str(n)


def save_aggregate(df, name, count_cols=None):
    """Write an aggregate table, suppressing small counts in `count_cols`."""
    ensure_dirs()
    out = df.copy()
    for c in count_cols or []:
        out[c] = out[c].map(suppress)
    path = cfg.AGGREGATE_DIR / name
    out.to_csv(path, index=False)
    print(f"  wrote {path}")
    return path
