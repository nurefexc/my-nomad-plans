#!/bin/bash
# Initialize DB and handle migrations
set -e

# Ensure instance directory exists and is writable
mkdir -p instance
chmod 777 instance || true

if [ ! -d "migrations" ]; then
    echo "Initializing migrations directory..."
    mkdir -p migrations
    flask --app app:create_app db init || (rmdir migrations && echo "Could not init migrations, directory removed")
    
    if [ -d "migrations" ]; then
        # If database exists, it might have an old alembic_version table
    # that references a non-existent revision (causing "Can't locate revision" errors)
    # We attempt to clear it if it exists to allow a fresh start of the migration history.
    DB_PATH="instance/nomad.db"
    if [ -f "$DB_PATH" ]; then
        echo "Database exists, checking for old migration metadata..."
        # Use python to safely check and drop the alembic_version table if it exists
        python3 -c "import sqlite3; conn=sqlite3.connect('$DB_PATH'); cursor=conn.cursor(); cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version';\"); row=cursor.fetchone(); 
if row:
    print('Found old alembic_version table, clearing it for fresh migration history...');
    cursor.execute('DROP TABLE alembic_version;');
    conn.commit();
conn.close();" || true
    fi

    if [ -d "migrations" ]; then
        echo "Generating initial migration..."
        if flask --app app:create_app db migrate -m "Initial migration"; then
            echo "Initial migration generated. Syncing database state..."
            flask --app app:create_app db stamp head || echo "Warning: Could not stamp database."
        else
            echo "Warning: Could not generate initial migration automatically. If the database is already initialized, you might need to stamp it manually."
        fi
    fi
    fi
fi

echo "Applying database migrations..."
if [ -d "migrations" ]; then
    flask --app app:create_app db upgrade || echo "Migration upgrade failed."
else
    echo "Migrations directory not found, using db.create_all() via app initialization."
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