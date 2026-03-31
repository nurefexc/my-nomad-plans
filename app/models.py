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
    trips = db.relationship('Trip', backref='owner', lazy=True)

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
    accommodation = db.Column(db.String(200)) # Sensitive info
    attractions = db.Column(db.Text) # Sights, plans
    notes = db.Column(db.Text)
    
    # New detailed fields
    transport_mode = db.Column(db.String(100)) # e.g. Flight, Train, Bus
    flight_number = db.Column(db.String(50))
    packing_list = db.Column(db.Text)
    expense_estimate = db.Column(db.Text) # Break down of expected costs
    visa_required = db.Column(db.Boolean, default=False)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    checklist = db.relationship('TripChecklist', backref='trip', lazy=True, cascade="all, delete-orphan")
    # tokens = db.relationship('ShareToken', backref='trip', lazy=True)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)

    @staticmethod
    def generate_token():
        return secrets.token_hex(16)
