import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    api_key TEXT NOT NULL
)
"""

conn = sqlite3.connect("test3.db")
conn.executescript(f"PRAGMA journal_mode=WAL;\n{_SCHEMA}")
conn.close()

# Verify
c = sqlite3.connect("test3.db")
print(c.execute("PRAGMA journal_mode").fetchone()[0])
c.close()
