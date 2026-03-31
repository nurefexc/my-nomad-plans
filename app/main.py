import json
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import login_required, current_user
from .models import Trip, ShareToken, User, TripChecklist
from . import db
from datetime import datetime
from country_list import countries_for_language
from urllib.parse import urljoin


main = Blueprint('main', __name__)

def get_version():
    try:
        manifest_path = os.path.join(current_app.root_path, '..', 'manifest.json')
        with open(manifest_path, 'r') as f:
            data = json.load(f)
            return data.get('version', 'unknown')
    except:
        return '1.0.0'

@main.context_processor
def inject_version():
    return dict(app_version=get_version())

def get_countries():
    # country_list provides tuple (iso_code, name)
    # We'll use names for our application as requested before
    return sorted([name for code, name in countries_for_language('en')])

@main.route('/')
def index():
    return render_template('index.html')

@main.route('/profile')
@login_required
def profile():
    trips = current_user.trips
    
    # Statistics
    visited_trips = [t for t in trips if t.status == 'visited']
    visited_countries = set([t.country for t in visited_trips])
    planned_trips = [t for t in trips if t.status == 'planned']
    all_planned_countries = set([t.country for t in planned_trips])
    
    # Advanced Stats: Percentage of world visited (calculated from country_list)
    available_countries = countries_for_language('en')
    world_countries_count = len(available_countries)
    visited_percent = round((len(visited_countries) / world_countries_count) * 100, 1) if world_countries_count > 0 else 0
    
    # Calculate more detailed stats
    # For example, countries yet to visit
    unvisited_countries_count = world_countries_count - len(visited_countries)
    
    stats = {
        'visited_count': len(visited_countries),
        'planned_count': len(all_planned_countries),
        'total_trips': len(trips),
        'visited_percent': visited_percent,
        'world_total': world_countries_count,
        'unvisited_count': unvisited_countries_count
    }
    
    return render_template('profile.html', name=current_user.name, trips=trips, stats=stats, now_date=datetime.now().date().strftime('%Y-%m-%d'))

@main.route('/trip/add', methods=['GET', 'POST'])
@login_required
def add_trip():
    if request.method == 'POST':
        destination = request.form.get('destination')
        country = request.form.get('country')
        latitude = float(request.form.get('latitude')) if request.form.get('latitude') else None
        longitude = float(request.form.get('longitude')) if request.form.get('longitude') else None
        
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        status = request.form.get('status')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        
        # Validation
        if status == 'planned' and not start_date:
            flash('Start date is required for planned trips!')
            return redirect(url_for('main.add_trip'))
        if status == 'visited':
            if not start_date or not end_date:
                flash('Both start and end dates are required for visited trips!')
                return redirect(url_for('main.add_trip'))
            if end_date > datetime.now().date():
                flash('Visited trip end date cannot be in the future!')
                return redirect(url_for('main.add_trip'))

        budget = float(request.form.get('budget')) if request.form.get('budget') else None
        accommodation = request.form.get('accommodation')
        attractions = request.form.get('attractions')
        notes = request.form.get('notes')
        
        # New fields
        transport_mode = request.form.get('transport_mode')
        flight_number = request.form.get('flight_number')
        packing_list = request.form.get('packing_list')
        expense_estimate = request.form.get('expense_estimate')
        visa_required = True if request.form.get('visa_required') else False

        new_trip = Trip(destination=destination, country=country, 
                        latitude=latitude, longitude=longitude,
                        start_date=start_date, end_date=end_date, 
                        status=status, budget=budget, 
                        accommodation=accommodation, attractions=attractions, 
                        notes=notes, transport_mode=transport_mode,
                        flight_number=flight_number, packing_list=packing_list,
                        expense_estimate=expense_estimate, visa_required=visa_required,
                        owner=current_user)
        
        db.session.add(new_trip)
        db.session.commit()
        
        flash('Trip successfully added!')
        return redirect(url_for('main.profile'))

    countries = get_countries()
    return render_template('add_trip.html', countries=countries)

@main.route('/trip/edit/<int:trip_id>', methods=['GET', 'POST'])
@login_required
def edit_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner != current_user:
        abort(403)
    
    if trip.status == 'visited':
        flash('Visited trips cannot be edited anymore.')
        return redirect(url_for('main.profile'))
    
    if request.method == 'POST':
        trip.destination = request.form.get('destination')
        trip.country = request.form.get('country')
        trip.latitude = float(request.form.get('latitude')) if request.form.get('latitude') else None
        trip.longitude = float(request.form.get('longitude')) if request.form.get('longitude') else None
        
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        status = request.form.get('status')
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
        
        # Validation
        if status == 'planned' and not start_date:
            flash('Start date is required for planned trips!')
            return redirect(url_for('main.edit_trip', trip_id=trip_id))
        if status == 'visited':
            if not start_date or not end_date:
                flash('Both start and end dates are required for visited trips!')
                return redirect(url_for('main.edit_trip', trip_id=trip_id))
            if end_date > datetime.now().date():
                flash('Visited trip end date cannot be in the future!')
                return redirect(url_for('main.edit_trip', trip_id=trip_id))

        trip.start_date = start_date
        trip.end_date = end_date
        trip.status = status
        trip.budget = float(request.form.get('budget')) if request.form.get('budget') else None
        trip.accommodation = request.form.get('accommodation')
        trip.attractions = request.form.get('attractions')
        trip.notes = request.form.get('notes')
        
        # New fields
        trip.transport_mode = request.form.get('transport_mode')
        trip.flight_number = request.form.get('flight_number')
        trip.packing_list = request.form.get('packing_list')
        trip.expense_estimate = request.form.get('expense_estimate')
        trip.visa_required = True if request.form.get('visa_required') else False

        db.session.commit()
        flash('Trip successfully updated!')
        return redirect(url_for('main.profile'))

    countries = get_countries()
    return render_template('edit_trip.html', trip=trip, countries=countries)

@main.route('/trip/delete/<int:trip_id>', methods=['POST'])
@login_required
def delete_trip(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner != current_user:
        abort(403)
    
    if trip.status == 'visited':
        flash('Cannot delete a trip that has already been visited!')
        return redirect(url_for('main.profile'))
    
    db.session.delete(trip)
    db.session.commit()
    flash('Trip deleted.')
    return redirect(url_for('main.profile'))

@main.route('/trip/set-planned/<int:trip_id>', methods=['POST'])
@login_required
def set_planned(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner != current_user:
        abort(403)
    
    if trip.status == 'draft':
        trip.status = 'planned'
        db.session.commit()
        flash(f'Trip to {trip.destination} is now planned!')
    
    return redirect(url_for('main.profile'))

@main.route('/trip/share', methods=['POST'])
@login_required
def share_trips():
    trip_ids = request.form.getlist('trip_ids')
    if not trip_ids:
        flash('No trips selected for sharing.')
        return redirect(url_for('main.profile'))
    
    # Verify ownership
    for tid in trip_ids:
        trip = Trip.query.get(int(tid))
        if not trip or trip.owner != current_user:
            abort(403)
    
    ids_str = ','.join(trip_ids)
    token_str = ShareToken.generate_token()
    new_token = ShareToken(token=token_str, trip_ids=ids_str)
    db.session.add(new_token)
    db.session.commit()
    
    # Build public URL using PUBLIC_BASE_URL if provided; otherwise fall back to Flask external URL
    public_base = current_app.config.get('PUBLIC_BASE_URL')
    if public_base:
        path = url_for('main.shared_view', token=token_str, _external=False)
        share_url = urljoin(public_base.rstrip('/') + '/', path.lstrip('/'))
    else:
        share_url = url_for('main.shared_view', token=token_str, _external=True)
    flash(f'Multi-trip sharing link created: {share_url}')
    return redirect(url_for('main.profile'))

@main.route('/trip/mark-visited/<int:trip_id>', methods=['POST'])
@login_required
def mark_visited(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner != current_user:
        abort(403)
    
    end_date_str = request.form.get('end_date')
    if not end_date_str:
        flash('End date is required to mark a trip as visited!')
        return redirect(url_for('main.profile'))
    
    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        if end_date > datetime.now().date():
            flash('End date cannot be in the future!')
            return redirect(url_for('main.profile'))
            
        trip.end_date = end_date
        trip.status = 'visited'
        db.session.commit()
        flash(f'Trip to {trip.destination} marked as visited!')
    except ValueError:
        flash('Invalid date format.')
        
    return redirect(url_for('main.profile'))

@main.route('/trip/<int:trip_id>/checklist/add', methods=['POST'])
@login_required
def add_checklist_item(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner != current_user:
        abort(403)
    
    if trip.status == 'visited':
        return jsonify({'error': 'Cannot add items to a visited trip'}), 403
    
    item = request.form.get('item')
    if not item:
        return jsonify({'error': 'Item text is required'}), 400
        
    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    
    new_item = TripChecklist(trip_id=trip.id, item=item, start_date=start_date, end_date=end_date)
    db.session.add(new_item)
    db.session.commit()
    
    return jsonify({
        'id': new_item.id,
        'item': new_item.item,
        'is_done': new_item.is_done,
        'start_date': str(new_item.start_date) if new_item.start_date else None,
        'end_date': str(new_item.end_date) if new_item.end_date else None
    })

@main.route('/checklist/toggle/<int:item_id>', methods=['POST'])
@login_required
def toggle_checklist_item(item_id):
    item = TripChecklist.query.get_or_404(item_id)
    if item.trip.owner != current_user:
        abort(403)
        
    item.is_done = not item.is_done
    db.session.commit()
    return jsonify({'id': item.id, 'is_done': item.is_done})

@main.route('/checklist/delete/<int:item_id>', methods=['POST'])
@login_required
def delete_checklist_item(item_id):
    item = TripChecklist.query.get_or_404(item_id)
    if item.trip.owner != current_user:
        abort(403)
        
    if item.trip.status == 'visited':
        return jsonify({'error': 'Cannot delete items from a visited trip'}), 403
        
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True})

@main.route('/shared/<token>')
def shared_view(token):
    share_token = ShareToken.query.filter_by(token=token).first_or_404()
    
    trip_ids = [int(tid) for tid in share_token.trip_ids.split(',')]
    trips = Trip.query.filter(Trip.id.in_(trip_ids)).all()
    
    shared_trips_data = []
    for trip in trips:
        checklist_data = []
        for item in trip.checklist:
            checklist_data.append({
                'item': item.item,
                'is_done': item.is_done,
                'start_date': item.start_date,
                'end_date': item.end_date
            })
            
        shared_trips_data.append({
            'destination': trip.destination,
            'country': trip.country,
            'start_date': trip.start_date,
            'end_date': trip.end_date,
            'attractions': trip.attractions,
            'notes': trip.notes,
            'latitude': trip.latitude,
            'longitude': trip.longitude,
            'status': trip.status,
            'transport_mode': trip.transport_mode,
            'flight_number': trip.flight_number,
            'visa_required': trip.visa_required,
            'checklist': checklist_data
        })
    
    return render_template('shared_trip.html', trips=shared_trips_data)
