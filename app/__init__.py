import os
import click
from flask import Flask
from flask.cli import with_appcontext
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()

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

    from .models import User, Trip, ShareToken

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
        db.session.add(user)
        db.session.commit()
        print(f"User {name} ({email}) created successfully!")

    @app.cli.command("seed-demo")
    @with_appcontext
    def seed_demo_command():
        """Seeds the database with demo data."""
        from seed_demo import seed_demo_data
        seed_demo_data()

    with app.app_context():
        # Fallback to create_all() ONLY if DB file doesn't exist and we are NOT running a migration/CLI command
        # This prevents locking issues during 'flask db init/migrate'
        import sys
        is_cli = len(sys.argv) > 1 and sys.argv[1] in ('db', 'create-user', 'seed-demo')
        
        # Use normalized URI from config
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if not is_cli and db_uri.startswith('sqlite:///'):
            db_path = db_uri.replace('sqlite:///', '')
            # If it was an absolute path (4 slashes), it now starts with /
            # If it was relative (3 slashes), it's already relative
            if not os.path.isabs(db_path):
                db_path = os.path.abspath(os.path.join(app.root_path, '..', db_path))
            
            if not os.path.exists(db_path):
                try:
                    db.create_all()
                    # Ensure the newly created database file is writable
                    if os.path.exists(db_path):
                        os.chmod(db_path, 0o666)
                except Exception as e:
                    app.logger.error(f"Failed to create database tables: {e}")
        pass

    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app

@login_manager.user_loader
def load_user(user_id):
    from .models import User
    return User.query.get(int(user_id))
