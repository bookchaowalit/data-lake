"""Helpers to provision ephemeral lab databases for offline multi-engine tests."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import uuid
from contextlib import contextmanager
from typing import Iterator


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _wait_tcp(host: str, port: int, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError as exc:
            last_err = exc
            time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {host}:{port}: {last_err}")


@contextmanager
def ephemeral_postgres(
    *,
    image: str = "postgres:16-alpine",
    user: str = "lake_lab",
    password: str = "lake_lab",
    database: str = "lake_lab",
) -> Iterator[str]:
    """Start a throwaway Postgres container; yield a psycopg DSN."""
    if not _docker_available():
        raise RuntimeError("Docker is required for ephemeral PostgreSQL lab runtime")

    port = _free_port()
    name = f"se-lake-pg-lab-{uuid.uuid4().hex[:10]}"
    cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-e",
        f"POSTGRES_USER={user}",
        "-e",
        f"POSTGRES_PASSWORD={password}",
        "-e",
        f"POSTGRES_DB={database}",
        "-p",
        f"127.0.0.1:{port}:5432",
        image,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _wait_tcp("127.0.0.1", port, timeout_s=90.0)
        # Wait until ready for SQL.
        deadline = time.time() + 90.0
        dsn = f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}"
        while time.time() < deadline:
            try:
                import psycopg  # type: ignore

                with psycopg.connect(dsn, connect_timeout=2) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        else:
            raise TimeoutError("PostgreSQL container did not become ready")
        yield dsn
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


@contextmanager
def optional_env_postgres() -> Iterator[str | None]:
    """Use LAKE_LAB_POSTGRES_DSN when set; otherwise ephemeral docker."""
    existing = (os.environ.get("LAKE_LAB_POSTGRES_DSN") or "").strip()
    if existing:
        yield existing
        return
    if not _docker_available():
        yield None
        return
    with ephemeral_postgres() as dsn:
        yield dsn
