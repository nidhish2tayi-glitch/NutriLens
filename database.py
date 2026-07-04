import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DATABASE_PATH = os.getenv("DATABASE_PATH", "../database/nutrilens.db")


def _resolve_db_path() -> str:
    if os.path.isabs(DATABASE_PATH):
        path = DATABASE_PATH
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DATABASE_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


DB_PATH = _resolve_db_path()


_SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL,
        ingredients_text TEXT NOT NULL,
        image_url TEXT,
        barcode TEXT,
        analysis_json TEXT NOT NULL,
        overall_score INTEGER NOT NULL
    )
"""


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(_SCHEMA_SQL)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection():
        pass


def save_scan(
    product_name: str,
    source: str,
    ingredients_text: str,
    analysis: Dict[str, Any],
    image_url: Optional[str] = None,
    barcode: Optional[str] = None,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    overall_score = int(analysis.get("scores", {}).get("overall", 0))
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scans
                (product_name, source, created_at, ingredients_text,
                 image_url, barcode, analysis_json, overall_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product_name,
                source,
                created_at,
                ingredients_text,
                image_url,
                barcode,
                json.dumps(analysis),
                overall_score,
            ),
        )
        return cursor.lastrowid


def list_scans() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, product_name, source, created_at, overall_score
            FROM scans
            ORDER BY id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_scan(scan_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM scans WHERE id = ?", (scan_id,)
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["analysis"] = json.loads(record.pop("analysis_json"))
        return record
