import sqlite3

def get_user(conn: sqlite3.Connection, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

def search_users(conn: sqlite3.Connection, name: str):
    # name comes from the ?q= query parameter
    return conn.execute(f"SELECT * FROM users WHERE name LIKE '%{name}%'").fetchall()
