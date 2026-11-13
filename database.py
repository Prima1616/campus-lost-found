import sqlite3

DB_NAME = "campus_lost_found.db"
STUDENTS_TO_ADD = [
    ("A910119824022", "Prima Paul", "PP022"),   # Student 1 
    ("A910119824024", "Rikita Sarma", "RS024"),   # Student 2
    ("A910119824012", "Sambridhi Roy", "SR012"),   # Student 3
    ("A910119824013", "Anuchandra Tewari", "AT013"),   # Student 4
]

GUARDS_TO_ADD = [
    ("GD101", "Ramesh Singh", "RS101"),   # Guard 1
    ("GD102", "Suresh Kumar", "SK102"),   # Guard 2
]
# =====================================================================


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS found_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT UNIQUE,
            finder_id TEXT NOT NULL,
            object_name TEXT NOT NULL,
            color TEXT NOT NULL,
            location TEXT NOT NULL,
            spot_note TEXT,
            description TEXT,
            image_path TEXT,
            found_date TEXT NOT NULL,
            status TEXT DEFAULT 'Pending Drop-Off',
            claimed_by_name TEXT,
            claimed_by_id TEXT,
            claimed_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lost_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            object_name TEXT NOT NULL,
            color TEXT NOT NULL,
            location TEXT NOT NULL,
            spot_note TEXT,
            lost_date TEXT NOT NULL,
            status TEXT DEFAULT 'Active'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    for uid, name, pwd in STUDENTS_TO_ADD:
        if uid.strip() and name.strip() and pwd.strip():
            cur.execute(
                "INSERT OR IGNORE INTO users (user_id, name, password, role) VALUES (?, ?, ?, 'student')",
                (uid.strip(), name.strip(), pwd.strip())
            )

    for g_id, g_name, g_pwd in GUARDS_TO_ADD:
        if g_id.strip() and g_name.strip() and g_pwd.strip():
            cur.execute(
                "INSERT OR IGNORE INTO users (user_id, name, password, role) VALUES (?, ?, ?, 'guard')",
                (g_id.strip(), g_name.strip(), g_pwd.strip())
            )

    conn.commit()
    conn.close()