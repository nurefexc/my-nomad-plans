# Nomad Planner

Nomad Planner is a Flask-based travel planning app for tracking trips, sharing itineraries, and viewing travel progress with map, calendar, stats, badges, and Immich gallery integration.

## Highlights

- Trip lifecycle: `draft`, `planned`, `visited`
- Shareable public trip pages with tokenized links
- Transport segments with sensitive/public visibility
- Immich photo and video album support
- Calendar and statistics dashboards
- English/Hungarian localization (language can be switched without login)
- Docker-first deployment with Gunicorn

## Project Layout

- App entry: `app.py`
- Flask package: `app/`
- Docker files: `docker/`
- SQLite data volume (default): `instance/`

## Quick Start (Docker)

From the repository root:

```bash
cp docker/.env.sample docker/.env
docker compose -f docker/docker-compose.yml up --build
```

App URL:

- `http://localhost:5000`

Create a user:

```bash
docker compose -f docker/docker-compose.yml exec web flask create-user "Your Name" your@email.com "strong-password"
```

Optional demo seed:

```bash
docker compose -f docker/docker-compose.yml exec web flask seed-demo
```

Stop:

```bash
docker compose -f docker/docker-compose.yml down
```

## Configuration

Main runtime config lives in `docker/.env`.

Common variables:

- `SECRET_KEY`
- `DATABASE_URL` (defaults to SQLite in `instance/nomad.db`)
- `PUBLIC_BASE_URL`
- `DEFAULT_CURRENCY`
- `IMMICH_ENABLED`
- `IMMICH_BASE_URL`
- `IMMICH_API_KEY`
- `IMMICH_TIMEOUT`
- `IMMICH_RETRY_COUNT`

## Migrations and SQLite Notes

Nomad Planner uses Flask-Migrate/Alembic. In Docker, startup logic in `docker/entrypoint.sh` attempts to keep SQLite schema in sync and recover from legacy migration metadata.

Useful commands (inside Docker):

```bash
docker compose -f docker/docker-compose.yml exec web flask --app app:create_app db current
docker compose -f docker/docker-compose.yml exec web flask --app app:create_app db migrate -m "Describe change"
docker compose -f docker/docker-compose.yml exec web flask --app app:create_app db upgrade
```

### Troubleshooting: `Cannot add a NOT NULL column with default value NULL`

This SQLite error appears when a migration tries to add a required column without a default on a table that already has rows.

Recommended fix pattern:

1. Add column as nullable or with server default.
2. Backfill existing rows.
3. Make it non-nullable in a follow-up migration (or keep default).

For this project specifically, container startup already backfills these columns safely when missing:

- `trip.currency` with default `USD`
- `user.default_currency` with default `USD`

If migration history is broken in a dev SQLite database, stop the stack, back up `instance/nomad.db`, then restart with a fresh migration state handled by the entrypoint.

## Local (Non-Docker) Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app:create_app db upgrade
flask --app app:create_app run
```

## Frontend Assets

Vendored assets are served locally from `app/static/vendor`:

- `leaflet`
- `flag-icons`
- `fullcalendar`

Main app UI files:

- `app/static/css/style.css`
- `app/static/js/ui.js`
- `app/static/js/immich_gallery.js`

## Security and Privacy

- No public signup page by default
- Share links use random tokens
- Sensitive transport fields are hidden from shared pages when marked private

## License

MIT License. See `LICENSE.md`.
