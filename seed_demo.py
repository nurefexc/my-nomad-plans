import os
from datetime import date, timedelta
from app import create_app, db
from app.models import User, Trip, TripChecklist

def seed_demo_data():
    app = create_app()
    with app.app_context():
        # Check if demo user already exists
        demo_email = 'demo@example.com'
        demo = User.query.filter_by(email=demo_email).first()
        
        if demo:
            print(f"User {demo_email} already exists. Cleaning up existing trips for this user...")
            Trip.query.filter_by(user_id=demo.id).delete()
            db.session.commit()
        else:
            print(f"Creating demo user: {demo_email}")
            demo = User(email=demo_email, name='Demo Traveler', is_admin=False)
            demo.set_password('demo123')
            db.session.add(demo)
            db.session.commit()

        # Add sample trips for demo user
        print("Adding sample trips and checklists...")
        trips = [
            Trip(destination='Budapest', country='Hungary', latitude=47.4979, longitude=19.0402,
                 start_date=date.today() - timedelta(days=60), end_date=date.today() - timedelta(days=50),
                 status='visited', budget=1200, accommodation='Downtown Apartment', 
                 transport_mode='Train',
                 attractions='Parliament, Fisherman\'s Bastion', notes='Great food and vibes.', owner=demo),
            Trip(destination='Lisbon', country='Portugal', latitude=38.7223, longitude=-9.1393,
                 start_date=date.today() - timedelta(days=20), end_date=date.today() - timedelta(days=10),
                 status='visited', budget=1500, accommodation='LX Factory Loft', 
                 transport_mode='Flight', flight_number='TP123',
                 attractions='Belem Tower, Alfama', notes='Loved the hills!', owner=demo),
            Trip(destination='Bali', country='Indonesia', latitude=-8.4095, longitude=115.1889,
                 start_date=date.today() + timedelta(days=30), end_date=date.today() + timedelta(days=60),
                 status='planned', budget=2500, accommodation='Eco Bamboo Villa', 
                 transport_mode='Flight', visa_required=True,
                 attractions='Ubud Monkey Forest, Tegallalang Rice Terrace', notes='Working from cafes.', owner=demo),
            Trip(destination='Tokyo', country='Japan', latitude=35.6762, longitude=139.6503,
                 start_date=None, end_date=None,
                 status='draft', budget=4000, accommodation='Shinjuku Hotel', 
                 packing_list='JR Pass, Power adapter',
                 attractions='Shibuya Crossing, Akihabara', notes='Still researching.', owner=demo)
        ]
        db.session.add_all(trips)
        db.session.commit()

        # Add some checklist items
        checklist_items = [
            TripChecklist(trip_id=trips[0].id, item='Buy Museum+ Pass', is_done=True),
            TripChecklist(trip_id=trips[2].id, item='Bali Spirit Festival', start_date=date.today() + timedelta(days=35), end_date=date.today() + timedelta(days=40)),
            TripChecklist(trip_id=trips[3].id, item='Find a good Sushi place', is_done=False)
        ]
        db.session.add_all(checklist_items)
        db.session.commit()
        print("Demo data seeded successfully! (demo@example.com / demo123)")

if __name__ == '__main__':
    seed_demo_data()
