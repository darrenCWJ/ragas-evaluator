"""Tiny persisted key-value store for runtime-toggleable app settings.

Settings that must survive restarts and be changeable from the UI without
touching .env (e.g. login enforcement). Values are strings; callers own
their parsing/validation.
"""

import db.init


def get_setting(conn, name: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE name = ?", (name,)).fetchone()
    return row["value"] if row is not None else default


def set_setting(conn, name: str, value: str) -> None:
    if db.init._USE_PG:
        conn.execute(
            "INSERT INTO app_settings (name, value, updated_at) VALUES (?, ?, NOW()) "
            "ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (name, value),
        )
    else:
        conn.execute(
            "INSERT INTO app_settings (name, value, updated_at) "
            "VALUES (?, ?, datetime('now', 'localtime')) "
            "ON CONFLICT(name) DO UPDATE SET value = excluded.value, "
            "updated_at = datetime('now', 'localtime')",
            (name, value),
        )
    conn.commit()
