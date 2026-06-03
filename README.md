# csv-to-sql

Convert CSV files into SQL `INSERT` statements with zero dependencies.

## Features

- **Auto-detect delimiter** — comma, tab, semicolon, or pipe
- **Type inference** — INTEGER, REAL, TEXT, BOOLEAN, DATE, NULL
- **Multiple dialects** — SQLite, MySQL, PostgreSQL, MSSQL, Oracle
- **Batch mode** — split large files into multi-row INSERTs
- **CREATE TABLE** generation with dialect-appropriate types
- **Pipe-friendly** — reads from stdin when no file given
- **Zero dependencies** — pure Python 3.7+

## Installation

```bash
git clone https://github.com/technicalanalysis00005-cell/csv-to-sql.git
cd csv-to-sql
# No install needed — just run it
python csv_to_sql.py --help
```

## Quick Start

```bash
# Basic conversion (SQLite dialect, auto-detect delimiter)
python csv_to_sql.py data.csv

# Custom table name + PostgreSQL dialect
python csv_to_sql.py data.csv -t users --dialect postgres

# Include CREATE TABLE statement
python csv_to_sql.py data.csv --create-table

# Batch mode: 100 rows per INSERT statement
python csv_to_sql.py data.csv --batch 100

# Read from stdin
cat data.csv | python csv_to_sql.py -

# Specify columns manually (skip header)
python csv_to_sql.py data.csv --no-header --columns "id,name,email"
```

## Dialect Support

| Dialect    | Identifier Quoting | Boolean Values | Example Type Mapping       |
|------------|--------------------|----------------|----------------------------|
| `sqlite`   | \`backticks\`      | 1/0            | `INTEGER`, `REAL`, `TEXT`  |
| `mysql`    | \`backticks\`      | 1/0            | `INT`, `DOUBLE`, `VARCHAR` |
| `postgres` | "double quotes"    | TRUE/FALSE     | `INTEGER`, `NUMERIC`, `VARCHAR` |
| `mssql`    | [brackets]         | 1/0            | `INT`, `FLOAT`, `NVARCHAR` |
| `oracle`   | "double quotes"    | 1/0            | `NUMBER`, `VARCHAR2`       |

## Examples

### Input (`users.csv`)
```csv
id,name,email,active,signup_date
1,Alice,alice@example.com,true,2024-01-15
2,Bob,bob@example.com,false,2024-02-20
3,Charlie,,yes,2024-03-10
```

### Command
```bash
python csv_to_sql.py users.csv -t users --dialect postgres --create-table
```

### Output
```sql
CREATE TABLE "users" (
    "id" INTEGER,
    "name" VARCHAR(255),
    "email" VARCHAR(255),
    "active" BOOLEAN,
    "signup_date" TIMESTAMP
);

INSERT INTO "users" ("id", "name", "email", "active", "signup_date") VALUES
    (1, 'Alice', 'alice@example.com', TRUE, '2024-01-15'),
    (2, 'Bob', 'bob@example.com', FALSE, '2024-02-20'),
    (3, 'Charlie', NULL, TRUE, '2024-03-10');
```

## Command Reference

```
usage: csv-to-sql [-h] [-t TABLE] [--schema SCHEMA]
                  [--dialect {sqlite,mysql,postgres,mssql,oracle}]
                  [--delimiter DELIMITER] [--no-header]
                  [--columns COLUMNS] [--create-table]
                  [--batch BATCH] [--limit LIMIT] [--version]
                  [file]

positional arguments:
  file                  CSV file path (use '-' or omit for stdin)

options:
  -t, --table TABLE     SQL table name (default: data)
  --schema SCHEMA       Schema prefix (e.g. public)
  --dialect DIALECT     SQL dialect (default: sqlite)
  --delimiter DELIMITER Force delimiter instead of auto-detect
  --no-header           First row is data, not headers
  --columns COLUMNS     Comma-separated column names
  --create-table        Prepend CREATE TABLE statement
  --batch BATCH         Max rows per INSERT (0 = all in one)
  --limit LIMIT         Only process first N rows (0 = all)
```

## License

MIT
