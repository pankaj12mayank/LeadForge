"""Start an embedded PostgreSQL instance on a fixed port for local dev/tests.

Uses the PostgreSQL binaries bundled with the `pgserver` package so no system
PostgreSQL installation is required. Prints the DATABASE_URL to stdout.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

try:
    import pgserver
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pgserver is required: pip install pgserver") from exc

PGDATA = Path("C:/temp/pgdata_leadforge")
PORT = 54320
BIN = Path(pgserver.__file__).resolve().parent / "pginstall" / "bin"
PG_CTL = BIN / "pg_ctl.exe"
INITDB = BIN / "initdb.exe"
PG_ISREADY = BIN / "pg_isready.exe"


def main() -> None:
    PGDATA.mkdir(parents=True, exist_ok=True)
    if not (PGDATA / "PG_VERSION").exists():
        subprocess.run([str(INITDB), "-D", str(PGDATA), "-U", "postgres"], check=True)
    subprocess.run([str(PG_CTL), "-D", str(PGDATA), "-o", f"-p {PORT}", "start"], check=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        r = subprocess.run([str(PG_ISREADY), "-p", str(PORT)], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"postgresql+psycopg2://postgres:@127.0.0.1:{PORT}/postgres", flush=True)
            return
        time.sleep(0.5)
    raise SystemExit("postgres did not become ready")


if __name__ == "__main__":
    main()
