"""Datenbank-Modul für die Strafenkasse."""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "strafenkasse.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Erstellt alle Tabellen falls nicht vorhanden."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            spond_id    TEXT    UNIQUE,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS penalty_catalog (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            amount      REAL    NOT NULL,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS penalties (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id   INTEGER NOT NULL REFERENCES players(id),
            reason      TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            paid        INTEGER DEFAULT 0,
            event_id    TEXT,
            created_at  TEXT    DEFAULT (datetime('now')),
            paid_at     TEXT
        );
    """)

    # Standard-Strafenkatalog einfügen falls leer
    cursor = conn.execute("SELECT COUNT(*) FROM penalty_catalog")
    if cursor.fetchone()[0] == 0:
        defaults = [
            ("Spond nicht beantwortet", 2.00),
            ("Gelbe Karte", 5.00),
            ("Gelb-Rot", 10.00),
            ("Rote Karte", 15.00),
            ("Zu spät zum Training", 3.00),
            ("Trikot vergessen", 5.00),
        ]
        conn.executemany(
            "INSERT INTO penalty_catalog (name, amount) VALUES (?, ?)", defaults
        )

    conn.commit()
    conn.close()


# ── Spieler ──────────────────────────────────────────────────────────

def get_or_create_player(name: str, spond_id: str = None) -> dict:
    conn = get_connection()
    if spond_id:
        row = conn.execute(
            "SELECT * FROM players WHERE spond_id = ?", (spond_id,)
        ).fetchone()
        if row:
            conn.close()
            return dict(row)

    row = conn.execute(
        "SELECT * FROM players WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    if row:
        if spond_id and not row["spond_id"]:
            conn.execute(
                "UPDATE players SET spond_id = ? WHERE id = ?", (spond_id, row["id"])
            )
            conn.commit()
        conn.close()
        return dict(row)

    conn.execute(
        "INSERT INTO players (name, spond_id) VALUES (?, ?)", (name, spond_id)
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM players WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    conn.close()
    return dict(row)


def find_player(search: str) -> dict | None:
    """Sucht Spieler per Name (Teilsuche)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM players WHERE LOWER(name) LIKE LOWER(?)",
        (f"%{search}%",),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_players() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM players ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Strafenkatalog ───────────────────────────────────────────────────

def get_catalog() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM penalty_catalog ORDER BY amount"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_catalog_entry(name: str, amount: float) -> dict:
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO penalty_catalog (name, amount) VALUES (?, ?)",
        (name, amount),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM penalty_catalog WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    return dict(row)


def remove_catalog_entry(name: str) -> bool:
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM penalty_catalog WHERE LOWER(name) = LOWER(?)", (name,)
    )
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def find_catalog_entry(search: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM penalty_catalog WHERE LOWER(name) LIKE LOWER(?)",
        (f"%{search}%",),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Strafen ──────────────────────────────────────────────────────────

def add_penalty(player_id: int, reason: str, amount: float, event_id: str = None) -> dict:
    conn = get_connection()
    conn.execute(
        "INSERT INTO penalties (player_id, reason, amount, event_id) VALUES (?, ?, ?, ?)",
        (player_id, reason, amount, event_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM penalties WHERE id = last_insert_rowid()"
    ).fetchone()
    conn.close()
    return dict(row)


def get_penalties(player_id: int = None, only_unpaid: bool = False) -> list[dict]:
    conn = get_connection()
    query = """
        SELECT p.*, pl.name as player_name
        FROM penalties p
        JOIN players pl ON pl.id = p.player_id
        WHERE 1=1
    """
    params = []
    if player_id:
        query += " AND p.player_id = ?"
        params.append(player_id)
    if only_unpaid:
        query += " AND p.paid = 0"
    query += " ORDER BY pl.name, p.created_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_penalty_summary(only_unpaid: bool = True) -> list[dict]:
    """Zusammenfassung: Summe pro Spieler."""
    conn = get_connection()
    query = """
        SELECT pl.name, pl.id as player_id,
               COUNT(p.id) as anzahl,
               SUM(p.amount) as summe
        FROM penalties p
        JOIN players pl ON pl.id = p.player_id
    """
    if only_unpaid:
        query += " WHERE p.paid = 0"
    query += " GROUP BY pl.id ORDER BY summe DESC"

    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_paid(player_id: int) -> int:
    """Markiert alle offenen Strafen eines Spielers als bezahlt."""
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE penalties SET paid = 1, paid_at = datetime('now') WHERE player_id = ? AND paid = 0",
        (player_id,),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount


def get_total_open() -> float:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM penalties WHERE paid = 0"
    ).fetchone()
    conn.close()
    return row["total"]


def penalty_exists(player_id: int, event_id: str) -> bool:
    """Prüft ob für einen Spieler + Event bereits eine Strafe existiert."""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM penalties WHERE player_id = ? AND event_id = ?",
        (player_id, event_id),
    ).fetchone()
    conn.close()
    return row["cnt"] > 0
