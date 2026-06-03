#!/usr/bin/env python3
"""csv-to-sql — Convert CSV files to SQL INSERT statements.

Features:
  • Auto-detect delimiter (comma, tab, semicolon, pipe)
  • Type inference: INTEGER, REAL, TEXT, BOOLEAN, DATE, NULL
  • Multiple SQL dialects: SQLite, MySQL, PostgreSQL, MSSQL, Oracle
  • Batch mode: split large files into multi-row INSERTs
  • Custom table name, schema prefix
  • Header row auto-detection or manual column names
  • Pipe-friendly: reads from stdin when no file given
  • CREATE TABLE generation
  • Zero dependencies — pure Python 3.7+

Usage:
  python csv_to_sql.py data.csv                    # Basic usage
  python csv_to_sql.py data.csv -t users           # Custom table name
  python csv_to_sql.py data.csv --dialect postgres  # PostgreSQL syntax
  python csv_to_sql.py data.csv --create-table      # Include CREATE TABLE
  python csv_to_sql.py data.csv --batch 100         # 100 rows per INSERT
  cat data.csv | python csv_to_sql.py -              # Read from stdin
"""

import argparse
import csv
import io
import re
import sys
from datetime import datetime
from typing import List, Optional, Tuple


__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------

BOOLEAN_TRUE = {"true", "yes", "1", "on"}
BOOLEAN_FALSE = {"false", "no", "0", "off"}

DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),                          # 2024-01-15
    re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$"),    # 2024-01-15 13:45:00
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),                          # 01/15/2024
    re.compile(r"^\d{2}-\d{2}-\d{4}$"),                          # 15-01-2024
]


def infer_type(value: str) -> str:
    """Infer SQL type from a string value."""
    v = value.strip()
    if v == "" or v.lower() == "null":
        return "NULL"

    # Integer (check before boolean so "0" and "1" are numbers)
    try:
        int(v)
        return "INTEGER"
    except ValueError:
        pass

    # Real / Float
    try:
        float(v)
        return "REAL"
    except ValueError:
        pass

    # Boolean (only non-numeric boolean words)
    if v.lower() in BOOLEAN_TRUE or v.lower() in BOOLEAN_FALSE:
        return "BOOLEAN"

    # Date / DateTime
    for pat in DATE_PATTERNS:
        if pat.match(v):
            return "DATE"

    return "TEXT"


def resolve_column_type(types: List[str]) -> str:
    """Resolve a column type from all values in that column."""
    non_null = [t for t in types if t != "NULL"]
    if not non_null:
        return "TEXT"
    if all(t == "INTEGER" for t in non_null):
        return "INTEGER"
    if all(t in ("INTEGER", "REAL") for t in non_null):
        return "REAL"
    if all(t == "BOOLEAN" for t in non_null):
        return "BOOLEAN"
    if all(t == "DATE" for t in non_null):
        return "DATE"
    return "TEXT"


# ---------------------------------------------------------------------------
# SQL generation per dialect
# ---------------------------------------------------------------------------

DIALECT_QUOTES = {
    "sqlite":    ("`", "`"),
    "mysql":     ("`", "`"),
    "postgres":  ('"', '"'),
    "mssql":     ("[", "]"),
    "oracle":    ('"', '"'),
}

DIALECT_NULL = {
    "sqlite": "NULL",
    "mysql": "NULL",
    "postgres": "NULL",
    "mssql": "NULL",
    "oracle": "NULL",
}


def quote_ident(name: str, dialect: str) -> str:
    lq, rq = DIALECT_QUOTES.get(dialect, ("`", "`"))
    return f"{lq}{name}{rq}"


def format_value(value: str, col_type: str, dialect: str) -> str:
    """Format a single value for SQL output."""
    v = value.strip()
    if v == "" or v.lower() == "null":
        return "NULL"

    if col_type == "INTEGER":
        try:
            return str(int(v))
        except ValueError:
            pass

    if col_type == "REAL":
        try:
            return str(float(v))
        except ValueError:
            pass

    if col_type == "BOOLEAN":
        if v.lower() in BOOLEAN_TRUE:
            return "TRUE" if dialect in ("postgres",) else "1"
        return "FALSE" if dialect in ("postgres",) else "0"

    # Escape single quotes for string types
    escaped = v.replace("'", "''")
    if dialect == "mysql":
        escaped = escaped.replace("\\", "\\\\")
    return f"'{escaped}'"


def sql_type(col_type: str, dialect: str) -> str:
    """Map inferred type to dialect-specific SQL type."""
    mapping = {
        "sqlite":   {"INTEGER": "INTEGER", "REAL": "REAL", "TEXT": "TEXT", "BOOLEAN": "INTEGER", "DATE": "TEXT"},
        "mysql":    {"INTEGER": "INT", "REAL": "DOUBLE", "TEXT": "VARCHAR(255)", "BOOLEAN": "TINYINT(1)", "DATE": "DATETIME"},
        "postgres": {"INTEGER": "INTEGER", "REAL": "NUMERIC", "TEXT": "VARCHAR(255)", "BOOLEAN": "BOOLEAN", "DATE": "TIMESTAMP"},
        "mssql":    {"INTEGER": "INT", "REAL": "FLOAT", "TEXT": "NVARCHAR(255)", "BOOLEAN": "BIT", "DATE": "DATETIME2"},
        "oracle":   {"INTEGER": "NUMBER", "REAL": "NUMBER", "TEXT": "VARCHAR2(255)", "BOOLEAN": "NUMBER(1)", "DATE": "DATE"},
    }
    m = mapping.get(dialect, mapping["sqlite"])
    return m.get(col_type, "TEXT")


def generate_create_table(columns: List[str], types: List[str], table: str, dialect: str, schema: Optional[str]) -> str:
    """Generate a CREATE TABLE statement."""
    full_table = f"{quote_ident(schema, dialect)}.{quote_ident(table, dialect)}" if schema else quote_ident(table, dialect)
    lines = []
    for col, col_type in zip(columns, types):
        st = sql_type(col_type, dialect)
        lines.append(f"    {quote_ident(col, dialect)} {st}")
    cols = ",\n".join(lines)
    return f"CREATE TABLE {full_table} (\n{cols}\n);\n"


def generate_insert(rows: List[List[str]], columns: List[str], types: List[str],
                    table: str, dialect: str, schema: Optional[str],
                    batch_size: int = 0) -> str:
    """Generate INSERT statements."""
    full_table = f"{quote_ident(schema, dialect)}.{quote_ident(table, dialect)}" if schema else quote_ident(table, dialect)
    col_names = ", ".join(quote_ident(c, dialect) for c in columns)
    prefix = f"INSERT INTO {full_table} ({col_names}) VALUES\n"

    output_parts: List[str] = []

    if batch_size <= 0:
        batch_size = len(rows) or 1

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        value_lines = []
        for row in batch:
            vals = []
            for j, val in enumerate(row):
                ct = types[j] if j < len(types) else "TEXT"
                vals.append(format_value(val, ct, dialect))
            value_lines.append(f"    ({', '.join(vals)})")
        output_parts.append(prefix + ",\n".join(value_lines) + ";\n")

    return "\n".join(output_parts)


# ---------------------------------------------------------------------------
# Delimiter detection
# ---------------------------------------------------------------------------

def detect_delimiter(sample: str) -> str:
    """Detect CSV delimiter from a sample of the file."""
    candidates = [",", "\t", ";", "|"]
    best = ","
    best_score = 0
    for delim in candidates:
        reader = csv.reader(io.StringIO(sample), delimiter=delim)
        rows = list(reader)
        if len(rows) < 2:
            continue
        widths = [len(r) for r in rows]
        if len(set(widths)) == 1 and widths[0] > 1:
            score = widths[0] * len(rows)
            if score > best_score:
                best_score = score
                best = delim
    return best


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="csv-to-sql",
        description="Convert CSV files to SQL INSERT statements.",
    )
    p.add_argument("file", nargs="?", default="-",
                   help="CSV file path (use '-' or omit for stdin)")
    p.add_argument("-t", "--table", default="data",
                   help="SQL table name (default: data)")
    p.add_argument("--schema", default=None,
                   help="Schema prefix (e.g. public)")
    p.add_argument("--dialect", choices=["sqlite", "mysql", "postgres", "mssql", "oracle"],
                   default="sqlite", help="SQL dialect (default: sqlite)")
    p.add_argument("--delimiter", default=None,
                   help="Force delimiter instead of auto-detect")
    p.add_argument("--no-header", action="store_true",
                   help="First row is data, not headers")
    p.add_argument("--columns", default=None,
                   help="Comma-separated column names (overrides header)")
    p.add_argument("--create-table", action="store_true",
                   help="Prepend CREATE TABLE statement")
    p.add_argument("--batch", type=int, default=0,
                   help="Max rows per INSERT (0 = all in one)")
    p.add_argument("--limit", type=int, default=0,
                   help="Only process first N rows (0 = all)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> str:
    # Read input
    if args.file == "-" or args.file is None:
        raw = sys.stdin.read()
    else:
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()

    if not raw.strip():
        return "-- Empty input, nothing to convert.\n"

    # Detect delimiter
    delim = args.delimiter
    if delim is None:
        sample = "\n".join(raw.splitlines()[:20])
        delim = detect_delimiter(sample)
        if delim == "\t":
            delim = "\t"

    # Parse CSV
    reader = csv.reader(io.StringIO(raw), delimiter=delim)
    all_rows = list(reader)

    if not all_rows:
        return "-- No rows found.\n"

    # Headers
    if args.columns:
        columns = [c.strip() for c in args.columns.split(",")]
        data_rows = all_rows
    elif args.no_header:
        columns = [f"col_{i}" for i in range(len(all_rows[0]))]
        data_rows = all_rows
    else:
        columns = [c.strip() for c in all_rows[0]]
        data_rows = all_rows[1:]

    # Normalize column count
    num_cols = len(columns)
    data_rows = [row[:num_cols] + [""] * max(0, num_cols - len(row)) for row in data_rows]

    # Apply limit
    if args.limit > 0:
        data_rows = data_rows[:args.limit]

    # Infer types
    column_types = []
    for col_idx in range(num_cols):
        col_values = [row[col_idx] for row in data_rows]
        column_types.append(resolve_column_type([infer_type(v) for v in col_values]))

    # Generate SQL
    output_parts: List[str] = []

    if args.create_table:
        output_parts.append(generate_create_table(columns, column_types, args.table, args.dialect, args.schema))

    if data_rows:
        output_parts.append(generate_insert(data_rows, columns, column_types, args.table, args.dialect, args.schema, args.batch))
    else:
        output_parts.append(f"-- {len(columns)} columns detected but no data rows.\n")

    return "\n".join(output_parts)


def main():
    args = parse_args()
    result = run(args)
    sys.stdout.write(result)


if __name__ == "__main__":
    main()
