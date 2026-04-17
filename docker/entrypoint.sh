#!/bin/bash
# Initialize DB and handle migrations
set -e

# Ensure instance directory exists and is writable
mkdir -p instance
chmod 777 instance || true

ensure_sqlite_currency_columns() {
    local db_path="$1"
    [ -f "$db_path" ] || return 0

    python3 - <<PY
import sqlite3

db_path = "$db_path"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

def has_table(name):
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def has_column(table, column):
    cur.execute(f"PRAGMA table_info('{table}')")
    return any(row[1] == column for row in cur.fetchall())

if has_table('trip') and not has_column('trip', 'currency'):
    print("Backfilling trip.currency with default USD...")
    cur.execute("ALTER TABLE trip ADD COLUMN currency VARCHAR(8) NOT NULL DEFAULT 'USD'")

if has_table('user') and not has_column('user', 'default_currency'):
    print("Backfilling user.default_currency with default USD...")
    cur.execute("ALTER TABLE user ADD COLUMN default_currency VARCHAR(8) NOT NULL DEFAULT 'USD'")

conn.commit()
conn.close()
PY
}

if [ ! -f "migrations/env.py" ]; then
    echo "Initializing migrations directory..."
    # Clean partial/invalid migration scaffolding before re-init.
    rm -rf migrations
    flask --app app:create_app db init

    DB_PATH="instance/nomad.db"
    if [ -f "$DB_PATH" ]; then
        echo "Database exists, checking for old migration metadata..."
        python3 -c "import sqlite3; conn=sqlite3.connect('$DB_PATH'); cursor=conn.cursor(); cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version';\"); row=cursor.fetchone();
if row:
    print('Found old alembic_version table, clearing it for fresh migration history...')
    cursor.execute('DROP TABLE alembic_version;')
    conn.commit()
conn.close()" || true

        ensure_sqlite_currency_columns "$DB_PATH"
    fi

    echo "Generating initial migration..."
    flask --app app:create_app db migrate -m "Initial migration" || true
fi

ensure_sqlite_currency_columns "instance/nomad.db"

echo "Applying database migrations..."
if [ -f "migrations/env.py" ]; then
    flask --app app:create_app db upgrade || echo "Migration upgrade failed."
else
    echo "Migrations environment not found, skipping upgrade."
fi

# Run demo seeding if requested and script is available
if [ "$DEMO" = "1" ]; then
    if [ -f "seed_demo.py" ]; then
        echo "Seeding demo data..."
        flask --app app:create_app seed-demo || echo "Demo seeding failed or already applied."
    else
        echo "Warning: seed_demo.py not found, skipping demo seeding."
    fi
fi

# Compile translations if pybabel is available
if command -v pybabel &> /dev/null; then
    echo "Compiling translations..."
    pybabel compile -d app/translations
fi

# Start the application
exec gunicorn --bind 0.0.0.0:5000 "app:create_app()"