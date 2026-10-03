"""Bounded native ClickHouse import probe; a signal cannot kill the caller."""

from __future__ import annotations

import importlib.util
import subprocess
import sys


def probe_embedded_clickhouse() -> tuple[bool, str]:
    """Check chDB in this interpreter without importing its native code here."""
    if importlib.util.find_spec("chdb") is None:
        return False, "Embedded ClickHouse requires chdb"
    # Prevent core dumps containing process memory; Windows has no resource module.
    code = (
        "import sys\n"
        "if sys.platform != 'win32':\n"
        " import resource\n"
        " resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n"
        "import chdb\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "Embedded ClickHouse chdb import probe timed out"
    except OSError:
        return False, "Embedded ClickHouse chdb import probe could not start"
    if result.returncode < 0:
        return False, f"Embedded ClickHouse chdb import probe terminated by signal {-result.returncode}"
    if result.returncode != 0:
        return False, f"Embedded ClickHouse chdb import probe failed (exit {result.returncode})"
    return True, ""
