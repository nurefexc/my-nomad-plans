# Nomad Planner 🌍

A modern, GNOME-style digital nomad trip planning application built with Flask. It helps you track your travels, plan future trips, and share your journeys with others via interactive maps.

## Features ✨

- **Interactive Mapping**: Visualize your travels with a dynamic world map using Leaflet.js.
- **Trip Lifecycle**: Manage trips through `Draft`, `Planned`, and `Visited` statuses.
- **Detailed Planning**: Track transport modes, expenses, packing lists, and visa requirements.
- **Checklists**: Add events or tasks to each trip with optional dates.
- **Global Statistics**: See your progress with "World Explorer" metrics (visited vs. unvisited countries).
- **Secure Sharing**: Generate unique tokens to share specific trips or your entire journey.
- **CLI User Management**: Create users securely via the command line.
- **GNOME-inspired UI**: Clean, professional interface with "Plus Jakarta Sans" typography.

## Quick Start (Docker) 🐳

The easiest way to run Nomad Planner is using Docker Compose.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/nurefexc/my-nomad-plans.git
   cd my-nomad-plans
   ```

2. **Configure environment:**
   ```bash
   cp .env.sample .env
   # Edit .env with your own secret key and configuration
   ```

3. **Start the application:**
```bash
docker compose -f docker/docker-compose.yml up --build
```

4. **Create a user:**
   In a new terminal, run:
   ```bash
   docker exec -it nomad-planner flask create-user "Your Name" your@email.com "yourpassword"
   ```

5. **(Optional) Seed demo data:**
   Set `DEMO=1` in your `.env` or `docker-compose.yml` and restart, or run manually:
   ```bash
   docker exec -it nomad-planner flask seed-demo
   ```

6. **Access the app:**
   Open [http://localhost:5000](http://localhost:5000) in your browser.

## Manual Installation 🛠️

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.sample .env
   # Edit .env and your secret key
   ```

3. **Initialize the database:**
```bash
flask --app app:create_app db init
flask --app app:create_app db migrate -m "Initial migration"
flask --app app:create_app db upgrade
```

4. **Run the app:**
   ```bash
   flask run
   ```

## User Management 🔑

For security reasons, there is no public signup page. Use the CLI to manage users:

```bash
flask create-user <name> <email> <password> [--admin]
```

## Database Migrations 🗄️

Nomad Planner uses Flask-Migrate (Alembic) to handle database schema changes.

- **Initial Setup**: Handled automatically in Docker.
- **New Migration**: `flask db migrate -m "Description"`
- **Apply Changes**: `flask db upgrade`

If you encounter migration errors (e.g., "Can't locate revision"), the Docker entrypoint is designed to attempt a recovery by clearing migration metadata and performing a fresh synchronization while preserving your data.

## Technologies 💻

- **Backend**: Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-Login
- **Frontend**: Bootstrap 5, Leaflet.js, Overpass API (for destination lookup)
- **Data**: country_list, SQLite
- **Deployment**: Docker, Gunicorn

## License 📄

This project is licensed under the MIT License - see `LICENSE.md` for details.

---
**Author**: [nurefexc](https://github.com/nurefexc)
**Repository**: [my-nomad-plans](https://github.com/nurefexc/my-nomad-plans)