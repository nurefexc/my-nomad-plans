import os
import click
from flask import Flask, session
from .translations import TRANSLATIONS
from flask.cli import with_appcontext
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, inspect, text
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_babel import Babel, _

db = SQLAlchemy(metadata=MetaData(naming_convention={
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}))
login_manager = LoginManager()
migrate = Migrate()
babel = Babel()

def get_locale():
    from flask import request
    supported_languages = ('en', 'hu')

    # 1. Check URL parameter
    lang = (request.args.get('lang') or '').strip().lower()
    if lang in supported_languages:
        session['lang'] = lang
        if current_user.is_authenticated and getattr(current_user, 'preferred_language', None) != lang:
            current_user.preferred_language = lang
            db.session.commit()
        return lang
    
    # 2. Check session
    session_lang = (session.get('lang') or '').strip().lower()
    if session_lang in supported_languages:
        return session_lang

    # 3. Check authenticated user preference
    if current_user.is_authenticated:
        user_lang = (getattr(current_user, 'preferred_language', None) or '').strip().lower()
        if user_lang in supported_languages:
            session['lang'] = user_lang
            return user_lang
    
    # 4. Check browser language
    return request.accept_languages.best_match(list(supported_languages)) or 'en'

def create_app():
    app = Flask(__name__)
    
    # Load environment variables from .env file
    from dotenv import load_dotenv
    load_dotenv()

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
    app.config['DEBUG'] = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't')
    
    # URL Configuration for external links
    app.config['SERVER_NAME'] = os.environ.get('SERVER_NAME')
    app.config['PREFERRED_URL_SCHEME'] = os.environ.get('PREFERRED_URL_SCHEME', 'http')
    # Public/Internal URL configuration
    public_base = os.environ.get('PUBLIC_BASE_URL')
    if not public_base and app.config['SERVER_NAME']:
        scheme = app.config['PREFERRED_URL_SCHEME']
        public_base = f"{scheme}://{app.config['SERVER_NAME']}"
    
    app.config['PUBLIC_BASE_URL'] = public_base
    app.config['INTERNAL_URL'] = os.environ.get('INTERNAL_URL')
    app.config['IMMICH_ENABLED'] = os.environ.get('IMMICH_ENABLED', 'False').lower() in ('true', '1', 't', 'yes')
    app.config['IMMICH_BASE_URL'] = os.environ.get('IMMICH_BASE_URL')
    app.config['IMMICH_API_KEY'] = os.environ.get('IMMICH_API_KEY')
    app.config['IMMICH_TIMEOUT'] = int(os.environ.get('IMMICH_TIMEOUT', '10'))
    app.config['IMMICH_RETRY_COUNT'] = int(os.environ.get('IMMICH_RETRY_COUNT', '2'))
    app.config['DEFAULT_CURRENCY'] = os.environ.get('DEFAULT_CURRENCY', 'USD')

    # Ensure instance folder exists and is writable
    try:
        os.makedirs(app.instance_path, exist_ok=True)
        # Ensure the directory is writable and accessible
        if not os.access(app.instance_path, os.W_OK):
            os.chmod(app.instance_path, 0o777)
    except OSError as e:
        app.logger.error(f"Could not create or set permissions for instance path: {e}")

    # Set default database URL if not provided
    # Use 4 slashes for absolute path to ensure it works correctly on all systems
    instance_db_path = os.path.join(app.instance_path, "nomad.db")
    if not os.path.isabs(instance_db_path):
        instance_db_path = os.path.abspath(instance_db_path)
    
    default_db = f'sqlite:///{instance_db_path}'
    db_url = os.environ.get('DATABASE_URL', default_db)
    
    # Normalize relative SQLite paths to absolute ones
    if db_url.startswith('sqlite:///') and not db_url.startswith('sqlite:////'):
        rel_path = db_url.replace('sqlite:///', '')
        abs_path = os.path.abspath(os.path.join(app.root_path, '..', rel_path))
        db_url = f'sqlite:///{abs_path}'
        
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    migrate.init_app(app, db)
    babel.init_app(app, locale_selector=get_locale)
    
    # Add zip filter to Jinja2
    app.jinja_env.filters['zip'] = zip
    
    # Seed badges only after tables exist; schema migration is handled by entrypoint/CLI.
    with app.app_context():
        try:
            if inspect(db.engine).has_table('badge'):
                from .models import Badge
                import json

                badges_json_path = os.path.join(app.root_path, 'badges.json')
                if os.path.exists(badges_json_path):
                    with open(badges_json_path, 'r') as f:
                        badge_defs = json.load(f)
                else:
                    badge_defs = []

                changed = False
                for b_def in badge_defs:
                    existing_badge = Badge.query.filter_by(code=b_def['code']).first()
                    if not existing_badge:
                        db.session.add(Badge(
                            code=b_def['code'],
                            title=b_def['title'],
                            icon=b_def['icon'],
                            description=b_def['description'],
                        ))
                        changed = True
                    elif (
                        existing_badge.title != b_def['title']
                        or existing_badge.icon != b_def['icon']
                        or existing_badge.description != b_def['description']
                    ):
                        existing_badge.title = b_def['title']
                        existing_badge.icon = b_def['icon']
                        existing_badge.description = b_def['description']
                        changed = True

                if changed:
                    db.session.commit()
        except Exception as e:
            app.logger.error(f"Failed to seed badges: {e}")

    # Extract SQLite database path from URI to ensure parent directory exists
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(db_path)
        
        db_dir = os.path.dirname(db_path)
        if db_dir:
            try:
                os.makedirs(db_dir, exist_ok=True)
                if not os.access(db_dir, os.W_OK):
                    os.chmod(db_dir, 0o777)
            except OSError as e:
                app.logger.error(f"Could not create or set permissions for database directory {db_dir}: {e}")

    # Optional reverse proxy support (honor X-Forwarded-* headers)
    if os.environ.get('PROXY_FIX', '0').lower() in ('1', 'true', 't', 'yes'):
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix
            app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
        except Exception:
            pass

    from .models import User, Trip, ShareToken, Badge, UserBadge, TripTransportSegment

    # CLI commands
    @app.cli.command("create-user")
    @click.argument("name")
    @click.argument("email")
    @click.argument("password")
    @click.option("--admin", is_flag=True, default=False)
    @with_appcontext
    def create_user_command(name, email, password, admin):
        """Creates a new user via CLI."""
        from .models import User
        if User.query.filter_by(email=email).first():
            print(f"User with email {email} already exists.")
            return
        user = User(name=name, email=email, is_admin=admin)
        user.set_password(password)
        user.default_currency = app.config.get('DEFAULT_CURRENCY', 'USD')
        user.preferred_landing_page = 'profile'
        user.show_badge_toasts = True
        user.compact_mode = False
        user.immich_base_url = app.config.get('IMMICH_BASE_URL')
        user.immich_api_key = app.config.get('IMMICH_API_KEY')
        db.session.add(user)
        db.session.commit()
        print(f"User {name} ({email}) created successfully!")

    @app.cli.command("seed-demo")
    @with_appcontext
    def seed_demo_command():
        """Seeds the database with demo data."""
        from seed_demo import seed_demo_data
        seed_demo_data()

    @app.cli.command("sync-badges")
    @with_appcontext
    def sync_badges_command():
        """Syncs all users' badges based on their trip history."""
        from .main import evaluate_user_badges
        from .models import User
        users = User.query.all()
        for user in users:
            evaluate_user_badges(user)
        print("All user badges synced successfully!")

    with app.app_context():
        try:
            inspector = inspect(db.engine)

            if inspector.has_table('user'):
                user_cols = {c['name'] for c in inspector.get_columns('user')}
                user_ddl_by_col = {
                    'profile_image_url': "ALTER TABLE user ADD COLUMN profile_image_url VARCHAR(500)",
                    'preferred_language': "ALTER TABLE user ADD COLUMN preferred_language VARCHAR(8)",
                    'preferred_landing_page': "ALTER TABLE user ADD COLUMN preferred_landing_page VARCHAR(20) NOT NULL DEFAULT 'profile'",
                    'show_badge_toasts': "ALTER TABLE user ADD COLUMN show_badge_toasts BOOLEAN NOT NULL DEFAULT 1",
                    'compact_mode': "ALTER TABLE user ADD COLUMN compact_mode BOOLEAN NOT NULL DEFAULT 0",
                }
                for col_name, ddl in user_ddl_by_col.items():
                    if col_name in user_cols:
                        continue
                    db.session.execute(text(ddl))
                db.session.commit()

            if not inspector.has_table('trip_transport_segment'):
                TripTransportSegment.__table__.create(bind=db.engine)
            else:
                # Keep local SQLite installs working even if Alembic migrations were not applied.
                existing_cols = {c['name'] for c in inspector.get_columns('trip_transport_segment')}
                ddl_by_col = {
                    'label': "ALTER TABLE trip_transport_segment ADD COLUMN label VARCHAR(120)",
                    'carrier': "ALTER TABLE trip_transport_segment ADD COLUMN carrier VARCHAR(120)",
                    'ticket_ref': "ALTER TABLE trip_transport_segment ADD COLUMN ticket_ref VARCHAR(120)",
                    'document_ref': "ALTER TABLE trip_transport_segment ADD COLUMN document_ref VARCHAR(255)",
                    'is_sensitive': "ALTER TABLE trip_transport_segment ADD COLUMN is_sensitive BOOLEAN NOT NULL DEFAULT 1",
                    'order_index': "ALTER TABLE trip_transport_segment ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0",
                }

                for col_name, ddl in ddl_by_col.items():
                    if col_name in existing_cols:
                        continue
                    db.session.execute(text(ddl))
                db.session.commit()

            # Backfill one outbound segment from legacy fields when missing.
            trips = Trip.query.all()
            changed = False
            for trip in trips:
                if trip.transport_segments:
                    continue
                mode = (trip.transport_mode or '').strip()
                if not mode:
                    continue
                db.session.add(TripTransportSegment(
                    trip_id=trip.id,
                    segment_type='outbound',
                    mode=mode,
                    reference_code=(trip.flight_number or '').strip() or None,
                    is_sensitive=False,
                ))
                changed = True

            if changed:
                db.session.commit()
        except Exception as e:
            app.logger.error(f"Transport segment bootstrap failed: {e}")

    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    @app.context_processor
    def inject_i18n():
        lang = (session.get('lang') or '').strip().lower()
        if lang not in ('en', 'hu') and current_user.is_authenticated:
            lang = (getattr(current_user, 'preferred_language', None) or '').strip().lower()
        if lang not in ('en', 'hu'):
            lang = 'en'

        compact_mode = bool(session.get('compact_mode', False))
        show_badge_toasts = bool(session.get('show_badge_toasts', True))
        if current_user.is_authenticated:
            compact_mode = bool(getattr(current_user, 'compact_mode', compact_mode))
            show_badge_toasts = bool(getattr(current_user, 'show_badge_toasts', show_badge_toasts))

        return dict(
            current_lang=lang,
            app_compact_mode=compact_mode,
            app_show_badge_toasts=show_badge_toasts,
        )

    return app

@login_manager.user_loader
def load_user(user_id):
    from .models import User
    return User.query.get(int(user_id))
