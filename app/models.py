from . import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    name = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)
    default_currency = db.Column(db.String(8), nullable=False, default='USD', server_default='USD')
    preferred_language = db.Column(db.String(8), nullable=True)
    preferred_landing_page = db.Column(db.String(20), nullable=False, default='profile', server_default='profile')
    show_badge_toasts = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    compact_mode = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    immich_base_url = db.Column(db.String(255), nullable=True)
    immich_api_key = db.Column(db.String(255), nullable=True)
    profile_image_url = db.Column(db.String(500), nullable=True)
    trips = db.relationship('Trip', backref='owner', lazy=True)
    share_tokens = db.relationship('ShareToken', primaryjoin='User.id==ShareToken.user_id', foreign_keys='ShareToken.user_id', lazy=True)

    def set_password(self, password):
        self.password = generate_password_hash(password, method='scrypt')

    def check_password(self, password):
        return check_password_hash(self.password, password)

class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    destination = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default='draft') # 'draft', 'planned', 'visited'
    budget = db.Column(db.Float)
    currency = db.Column(db.String(8), nullable=False, default='USD', server_default='USD')
    accommodation = db.Column(db.String(200)) # Sensitive info
    attractions = db.Column(db.Text) # Sights, plans
    notes = db.Column(db.Text)
    
    # New detailed fields
    transport_mode = db.Column(db.String(100)) # e.g. Flight, Train, Bus
    flight_number = db.Column(db.String(50))
    packing_list = db.Column(db.Text)
    expense_estimate = db.Column(db.Text) # Break down of expected costs
    visa_required = db.Column(db.Boolean, default=False)
    immich_album_id = db.Column(db.String(64), nullable=True, unique=True, index=True)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    checklist = db.relationship('TripChecklist', backref='trip', lazy=True, cascade="all, delete-orphan")
    transport_segments = db.relationship(
        'TripTransportSegment',
        backref='trip',
        lazy=True,
        cascade="all, delete-orphan",
        order_by='TripTransportSegment.order_index',
    )
    # tokens = db.relationship('ShareToken', backref='trip', lazy=True)


class TripTransportSegment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False, index=True)
    segment_type = db.Column(db.String(32), nullable=False, default='other', server_default='other')
    label = db.Column(db.String(120), nullable=True)
    mode = db.Column(db.String(100), nullable=False)
    reference_code = db.Column(db.String(100), nullable=True)
    carrier = db.Column(db.String(120), nullable=True)
    ticket_ref = db.Column(db.String(120), nullable=True)
    document_ref = db.Column(db.String(255), nullable=True)
    is_sensitive = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    order_index = db.Column(db.Integer, nullable=False, default=0, server_default='0')

class TripChecklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trip.id'), nullable=False)
    item = db.Column(db.String(200), nullable=False)
    is_done = db.Column(db.Boolean, default=False)
    start_date = db.Column(db.Date) # Optional
    end_date = db.Column(db.Date) # Optional
    
class ShareToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(32), unique=True, nullable=False)
    # Trip IDs as a comma-separated string for multi-trip sharing
    trip_ids = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    view_count = db.Column(db.Integer, default=0)
    unique_view_count = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, nullable=True) # Optional owner id for filtering user's share links

    @staticmethod
    def generate_token():
        return secrets.token_hex(16)

class Badge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255))
    icon = db.Column(db.String(10)) # Emoji or icon class

class UserBadge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey('badge.id'), nullable=False)
    awarded_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_new = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref=db.backref('user_badges', lazy=True))
    badge = db.relationship('Badge', backref=db.backref('user_badges', lazy=True))
