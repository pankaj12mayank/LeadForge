"""Start an embedded PostgreSQL instance on a fixed port for local dev/tests.

Uses the PostgreSQL binaries bundled with the `pgserver` package so no system
PostgreSQL installation is required. Prints the DATABASE_URL to stdout.
Idempotent: if Postgres is already running on the port, just prints the URL.
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


def _ready() -> bool:
    r = subprocess.run([str(PG_ISREADY), "-p", str(PORT)], capture_output=True, text=True)
    return r.returncode == 0


def main() -> None:
    URL = f"postgresql+psycopg2://postgres:@127.0.0.1:{PORT}/postgres"
    if _ready():
        print(URL, flush=True)
        return

    PGDATA.mkdir(parents=True, exist_ok=True)
    if not (PGDATA / "PG_VERSION").exists():
        subprocess.run([str(INITDB), "-D", str(PGDATA), "-U", "postgres"], check=True)
    # Start may report "lock file exists" if another process owns it; ignore non-zero
    # and fall through to the ready-wait loop.
    subprocess.run([str(PG_CTL), "-D", str(PGDATA), "-o", f"-p {PORT}", "start"])

    deadline = time.time() + 30
    while time.time() < deadline:
        if _ready():
            print(URL, flush=True)
            return
        time.sleep(0.5)
    raise SystemExit("postgres did not become ready")


if __name__ == "__main__":
    main()
