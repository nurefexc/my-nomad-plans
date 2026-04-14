import json
import os
import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app, session
from flask_babel import _, get_locale
from flask_login import login_required, current_user
from .models import Trip, ShareToken, User, TripChecklist, Badge, UserBadge
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
    def get_country_code(country_name):
        if not country_name:
            return None
        # Try to find the code for the given English name
        for code, name in countries_for_language('en'):
            if name.lower() == country_name.lower():
                return code.lower()
        return None

    return dict(app_version=get_version(), get_country_code=get_country_code)

def get_countries():
    # country_list provides tuple (iso_code, name)
    # We'll use names for our application as requested before
    return sorted([name for code, name in countries_for_language('en')])

@main.route('/')
def index():
    return render_template('index.html')

@main.route('/set_language/<lang>')
def set_language(lang):
    if lang in ['en', 'hu']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('main.index'))

def get_eu_countries():
    """Fetches the list of EU countries from the official EU SPARQL endpoint."""
    url = "https://publications.europa.eu/webapi/rdf/sparql"
    query = """PREFIX euvoc: <http://publications.europa.eu/ontology/euvoc#>
PREFIX org: <http://www.w3.org/ns/org#>
PREFIX skosxl: <http://www.w3.org/2008/05/skos-xl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dct: <http://purl.org/dc/terms#>

SELECT distinct ?country_en
FROM  <http://publications.europa.eu/resource/authority/country> 
WHERE {
    Values ?organisation {
        <http://publications.europa.eu/resource/authority/corporate-body/EURUN>
    }
    ?country_uri a skos:Concept .
    ?country_uri euvoc:order ?protocol_order .
    ?country_uri org:hasMembership ?membership .
    ?membership org:organization ?organisation .
    ?country_uri skos:prefLabel ?country_label_en .
    Bind(str(?country_label_en) as ?country_en) .
    filter(lang(?country_label_en) = "en")
} order by ?protocol_order"""
    
    params = {
        'query': query,
        'format': 'application/sparql-results+json',
        'timeout': 0,
        'debug': 'on'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        countries = [row['country_en']['value'] for row in data['results']['bindings']]
        return set(countries)
    except Exception as e:
        current_app.logger.error(f"Error fetching EU countries: {e}")
        # Fallback to a hardcoded list if the online service is unavailable
        return {
            'Austria', 'Belgium', 'Bulgaria', 'Croatia', 'Cyprus', 'Czechia', 'Denmark',
            'Estonia', 'Finland', 'France', 'Germany', 'Greece', 'Hungary', 'Ireland',
            'Italy', 'Latvia', 'Lithuania', 'Luxembourg', 'Malta', 'Netherlands',
            'Poland', 'Portugal', 'Romania', 'Slovakia', 'Slovenia', 'Spain', 'Sweden'
        }

def get_regional_countries():
    """Returns sets of countries for different regions, attempting to fetch from an API first."""
    import json, os, requests
    from flask import current_app
    
    cache_path = os.path.join(current_app.instance_path, 'regional_countries.json')
    
    # Check if we have a fresh cache (less than 30 days old)
    import time
    if os.path.exists(cache_path) and (time.time() - os.path.getmtime(cache_path) < 30 * 24 * 60 * 60):
        try:
            with open(cache_path, 'r') as f:
                return {k: set(v) for k, v in json.load(f).items()}
        except Exception:
            pass

    # Try to fetch from API
    try:
        # Using restcountries.com API
        response = requests.get("https://restcountries.com/v3.1/all?fields=name,region", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        regional = {
            'africa': set(),
            'asia': set(),
            'americas': set(),
            'oceania': set()
        }
        
        for country in data:
            name = country.get('name', {}).get('common')
            region = country.get('region', '').lower()
            if name and region in regional:
                regional[region].add(name)
        
        # Cache the results
        try:
            with open(cache_path, 'w') as f:
                json.dump({k: list(v) for k, v in regional.items()}, f)
        except Exception:
            pass
            
        return regional
    except Exception as e:
        current_app.logger.error(f"Error fetching regional countries: {e}")
        # Fallback to hardcoded list
        return {
            'africa': {
                'Algeria', 'Angola', 'Benin', 'Botswana', 'Burkina Faso', 'Burundi', 'Cabo Verde', 'Cameroon',
                'Central African Republic', 'Chad', 'Comoros', 'Congo', 'Congo, Democratic Republic of the',
                'Djibouti', 'Egypt', 'Equatorial Guinea', 'Eritrea', 'Eswatini', 'Ethiopia', 'Gabon', 'Gambia',
                'Ghana', 'Guinea', 'Guinea-Bissau', 'Ivory Coast', 'Kenya', 'Lesotho', 'Liberia', 'Libya',
                'Madagascar', 'Malawi', 'Mali', 'Mauritania', 'Mauritius', 'Morocco', 'Mozambique', 'Namibia',
                'Niger', 'Nigeria', 'Rwanda', 'Sao Tome and Principe', 'Senegal', 'Seychelles', 'Sierra Leone',
                'Somalia', 'South Africa', 'South Sudan', 'Sudan', 'Tanzania', 'Togo', 'Tunisia', 'Uganda',
                'Zambia', 'Zimbabwe'
            },
            'asia': {
                'Afghanistan', 'Armenia', 'Azerbaijan', 'Bahrain', 'Bangladesh', 'Bhutan', 'Brunei', 'Cambodia',
                'China', 'Cyprus', 'Georgia', 'India', 'Indonesia', 'Iran', 'Iraq', 'Israel', 'Japan', 'Jordan',
                'Kazakhstan', 'Kuwait', 'Kyrgyzstan', 'Laos', 'Lebanon', 'Malaysia', 'Maldives', 'Mongolia',
                'Myanmar', 'Nepal', 'North Korea', 'Oman', 'Pakistan', 'Palestine', 'Philippines', 'Qatar',
                'Saudi Arabia', 'Singapore', 'South Korea', 'Sri Lanka', 'Syria', 'Taiwan', 'Tajikistan',
                'Thailand', 'Timor-Leste', 'Turkey', 'Turkmenistan', 'United Arab Emirates', 'Uzbekistan',
                'Vietnam', 'Yemen'
            },
            'americas': {
                'Antigua and Barbuda', 'Argentina', 'Bahamas', 'Barbados', 'Belize', 'Bolivia', 'Brazil', 'Canada',
                'Chile', 'Colombia', 'Costa Rica', 'Cuba', 'Dominica', 'Dominican Republic', 'Ecuador', 'El Salvador',
                'Grenada', 'Guatemala', 'Guyana', 'Haiti', 'Honduras', 'Jamaica', 'Mexico', 'Nicaragua', 'Panama',
                'Paraguay', 'Peru', 'Saint Kitts and Nevis', 'Saint Lucia', 'Saint Vincent and the Grenadines',
                'Suriname', 'Trinidad and Tobago', 'United States', 'Uruguay', 'Venezuela'
            },
            'oceania': {
                'Australia', 'Fiji', 'Kiribati', 'Marshall Islands', 'Micronesia', 'Nauru', 'New Zealand', 'Palau',
                'Papua New Guinea', 'Samoa', 'Solomon Islands', 'Tonga', 'Tuvalu', 'Vanuatu'
            }
        }

def evaluate_user_badges(user):
    """Evaluates and awards badges to a user based on their trip history and JSON definitions."""
    import os, json
    trips = user.trips
    visited_countries = set([t.country for t in trips if t.status == 'visited'])
    
    # Pre-calculate common criteria variables
    eu_countries = get_eu_countries()
    visited_eu = visited_countries.intersection(eu_countries)
    
    regional = get_regional_countries()
    africa_countries = regional['africa']
    asia_countries = regional['asia']
    americas_countries = regional['americas']
    oceania_countries = regional['oceania']
    
    visited_africa = visited_countries.intersection(africa_countries)
    visited_asia = visited_countries.intersection(asia_countries)
    visited_americas = visited_countries.intersection(americas_countries)
    visited_oceania = visited_countries.intersection(oceania_countries)
    
    awarded_codes = set([ub.badge.code for ub in user.user_badges])
    
    def award(code):
        if code not in awarded_codes:
            badge = Badge.query.filter_by(code=code).first()
            if badge:
                ub = UserBadge(user_id=user.id, badge_id=badge.id, is_new=True)
                db.session.add(ub)
                awarded_codes.add(code)
                return True
        return False

    changed = False
    badge_progress = []
    
    # Load definitions from JSON
    badges_json_path = os.path.join(current_app.root_path, 'badges.json')
    if os.path.exists(badges_json_path):
        try:
            with open(badges_json_path, 'r') as f:
                badge_defs = json.load(f)
            
            # Context for evaluation
            eval_context = {
                'len': len,
                'min': min,
                'max': max,
                'user': user,
                'trips': trips,
                'visited_countries': visited_countries,
                'eu_countries': eu_countries,
                'visited_eu': visited_eu,
                'africa_countries': africa_countries,
                'asia_countries': asia_countries,
                'americas_countries': americas_countries,
                'oceania_countries': oceania_countries,
                'visited_africa': visited_africa,
                'visited_asia': visited_asia,
                'visited_americas': visited_americas,
                'visited_oceania': visited_oceania
            }
            
            for b_def in badge_defs:
                code = b_def.get('code')
                criteria = b_def.get('criteria')
                progress_expr = b_def.get('progress')
                
                if code and criteria:
                    try:
                        # Evaluate if awarded
                        if eval(criteria, {"__builtins__": {}}, eval_context):
                            if award(code):
                                changed = True
                        
                        # Calculate progress and counts
                        progress = 0
                        current_val = 0
                        target_val = 0
                        
                        progress_expr = b_def.get('progress')
                        current_expr = b_def.get('current')
                        target_expr = b_def.get('target')

                        if progress_expr:
                            progress = eval(str(progress_expr), {"__builtins__": {}}, eval_context)
                        elif code in awarded_codes:
                            progress = 100
                        
                        if current_expr:
                            current_val = eval(str(current_expr), {"__builtins__": {}}, eval_context)
                        elif code in awarded_codes:
                            current_val = 1 # Fallback
                        
                        if target_expr:
                            if isinstance(target_expr, (int, float)):
                                target_val = target_expr
                            else:
                                target_val = eval(str(target_expr), {"__builtins__": {}}, eval_context)
                        elif code in awarded_codes:
                            target_val = current_val # Fallback
                            
                        badge_progress.append({
                            'code': code,
                            'title': b_def.get('title'),
                            'description': b_def.get('description'),
                            'icon': b_def.get('icon'),
                            'progress': progress,
                            'current': current_val,
                            'target': target_val,
                            'awarded': code in awarded_codes,
                            'is_new': any(ub.is_new for ub in user.user_badges if ub.badge.code == code)
                        })
                    except Exception as e:
                        current_app.logger.error(f"Error evaluating badge {code}: {e}")
        except Exception as e:
            current_app.logger.error(f"Error loading badges.json: {e}")
            
    if changed:
        db.session.commit()
    
    return badge_progress

@main.route('/profile')
@login_required
def profile():
    # Evaluate badges on profile view (initial or refresh)
    badge_data = evaluate_user_badges(current_user)

    # Mark new badges as not new anymore after they've been seen on this page
    # But only after we've passed them to the template
    user_badges = current_user.user_badges
    new_badges_count = sum(1 for ub in user_badges if ub.is_new)

    # Sort trips by start_date, moving None dates to the end
    trips = sorted(current_user.trips, key=lambda x: (x.start_date is None, x.start_date))

    # Calculate countdown for the next planned trip
    next_trip = None
    from datetime import datetime
    now = datetime.now().date()
    for trip in trips:
        if trip.status == 'planned' and trip.start_date and trip.start_date >= now:
            next_trip = trip
            break

    # Statistics
    visited_trips = [t for t in trips if t.status == 'visited']
    visited_countries = set([t.country for t in visited_trips])
    planned_trips = [t for t in trips if t.status == 'planned']
    all_planned_countries = set([t.country for t in planned_trips])
    
    # World visited count
    available_countries = countries_for_language('en')
    world_countries_count = len(available_countries)
    visited_percent = round((len(visited_countries) / world_countries_count) * 100, 1) if world_countries_count > 0 else 0
    unvisited_countries_count = world_countries_count - len(visited_countries)

    stats = {
        'visited_count': len(visited_countries),
        'planned_count': len(all_planned_countries),
        'total_trips': len(trips),
        'visited_percent': visited_percent,
        'world_total': world_countries_count,
        'unvisited_count': unvisited_countries_count
    }
    
    response = render_template('profile.html', 
                           name=current_user.name, 
                           trips=trips, 
                           stats=stats, 
                           badges=badge_data[:6], 
                           next_trip=next_trip,
                           now_date=datetime.now().date(), 
                           new_badges_count=new_badges_count)

    if new_badges_count > 0:
        for ub in user_badges:
            ub.is_new = False
        db.session.commit()
    
    return response

@main.route('/badges')
@login_required
def badges():
    # Evaluate badges
    badge_data = evaluate_user_badges(current_user)
    
    # Calculate some summary stats for the badge page
    total_badges = len(badge_data)
    awarded_badges = sum(1 for b in badge_data if b['awarded'])
    completion_percent = round((awarded_badges / total_badges) * 100) if total_badges > 0 else 0
    
    # Group badges by status (awarded first, then by progress)
    sorted_badges = sorted(badge_data, key=lambda x: (not x['awarded'], -x['progress']))
    
    return render_template('badges.html', 
                           badges=sorted_badges,
                           total_count=total_badges,
                           awarded_count=awarded_badges,
                           completion_percent=completion_percent)

@main.route('/stats')
@login_required
def stats():
    trips = current_user.trips
    visited_trips = [t for t in trips if t.status == 'visited']
    visited_countries = set([t.country for t in visited_trips])
    
    # Advanced Stats: Percentage of world visited (calculated from country_list)
    available_countries = countries_for_language('en')
    world_countries_count = len(available_countries)
    visited_percent = round((len(visited_countries) / world_countries_count) * 100, 1) if world_countries_count > 0 else 0
    unvisited_countries_count = world_countries_count - len(visited_countries)

    # More metrics
    total_budget = 0
    trips_by_year = {}
    longest_trip = None
    shortest_trip = None
    max_duration = -1
    min_duration = 99999
    
    for t in visited_trips:
        if t.start_date:
            year = t.start_date.year
            trips_by_year[year] = trips_by_year.get(year, 0) + 1
            if t.end_date:
                duration = (t.end_date - t.start_date).days
                if duration > max_duration:
                    max_duration = duration
                    longest_trip = t
                if duration < min_duration:
                    min_duration = duration
                    shortest_trip = t

        if t.budget:
            total_budget += t.budget

    # Detailed travel history
    monthly_stats = {}
    total_duration = 0
    countries_by_trips = {}
    for t in visited_trips:
        countries_by_trips[t.country] = countries_by_trips.get(t.country, 0) + 1
        if t.start_date:
            month_key = t.start_date.strftime('%Y-%m')
            monthly_stats[month_key] = monthly_stats.get(month_key, 0) + 1
            if t.end_date:
                duration = (t.end_date - t.start_date).days
                if duration > 0:
                    total_duration += duration

    # Sort monthly stats
    sorted_months = sorted(monthly_stats.keys())
    monthly_data = {
        'labels': [datetime.strptime(m, '%Y-%m').strftime('%b %y') for m in sorted_months],
        'values': [monthly_stats[m] for m in sorted_months],
        'zipped': list(zip([datetime.strptime(m, '%Y-%m').strftime('%b %y') for m in sorted_months], 
                      [monthly_stats[m] for m in sorted_months]))
    }

    # Top transport types
    transport_counts = {}
    for t in visited_trips:
        mode = getattr(t, 'transport_mode', getattr(t, 'transport', None))
        if mode:
            mode = mode.lower()
            transport_counts[mode] = transport_counts.get(mode, 0) + 1
    
    sorted_transport = sorted(transport_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_countries = sorted(countries_by_trips.items(), key=lambda x: x[1], reverse=True)[:5]

    planned_trips = [t for t in trips if t.status == 'planned']

    stats_data = {
        'visited_count': len(visited_countries),
        'world_total': world_countries_count,
        'visited_percent': visited_percent,
        'unvisited_count': unvisited_countries_count,
        'total_trips': len(trips),
        'total_visited': len(visited_trips),
        'total_planned': len(planned_trips),
        'total_days_traveled': total_duration,
        'avg_trip_length': round(total_duration / len(visited_trips), 1) if visited_trips else 0,
        'total_budget': total_budget,
        'avg_budget': round(total_budget / len(visited_trips), 2) if visited_trips else 0,
        'avg_budget_per_day': round(total_budget / total_duration, 2) if total_duration > 0 else 0,
        'monthly_data': monthly_data,
        'top_transport': sorted_transport,
        'top_countries': top_countries,
        'longest_trip': longest_trip,
        'shortest_trip': shortest_trip,
        'trips_by_year': sorted(trips_by_year.items(), reverse=True)
    }

    return render_template('stats.html', stats=stats_data)

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
            flash(_('Start date is required for planned trips!'))
            return redirect(url_for('main.add_trip'))
        if status == 'visited':
            if not start_date or not end_date:
                flash(_('Both start and end dates are required for visited trips!'))
                return redirect(url_for('main.add_trip'))
            if end_date > datetime.now().date():
                flash(_('Visited trip end date cannot be in the future!'))
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
        # Award badges after interaction
        evaluate_user_badges(current_user)
        flash(_('Trip added successfully!'))
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
        flash(_('Cannot edit a visited trip.'))
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
            flash(_('Start date is required for planned trips!'))
            return redirect(url_for('main.edit_trip', trip_id=trip_id))
        if status == 'visited':
            if not start_date or not end_date:
                flash(_('Both start and end dates are required for visited trips!'))
                return redirect(url_for('main.edit_trip', trip_id=trip_id))
            if end_date > datetime.now().date():
                flash(_('Visited trip end date cannot be in the future!'))
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
        flash(_('Trip updated successfully!'))
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
        flash(_('Cannot delete a visited trip.'))
        return redirect(url_for('main.profile'))
    
    db.session.delete(trip)
    db.session.commit()
    flash(_('Trip deleted successfully!'))
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
        flash(_('Trip status set to planned for {dest}.').format(dest=trip.destination))
    
    return redirect(url_for('main.profile'))

@main.route('/trip/share', methods=['POST'])
@login_required
def share_trips():
    trip_ids = request.form.getlist('trip_ids')
    if not trip_ids:
        flash(_('No trips selected for sharing!'))
        return redirect(url_for('main.profile'))
    
    title = request.form.get('title')
    description = request.form.get('description')
    expires_at_str = request.form.get('expires_at')
    expires_at = None
    if expires_at_str:
        try:
            expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d')
        except ValueError:
            pass

    # Verify ownership
    for tid in trip_ids:
        trip = Trip.query.get(int(tid))
        if not trip or trip.owner != current_user:
            abort(403)
    
    ids_str = ','.join(trip_ids)
    token_str = ShareToken.generate_token()
    new_token = ShareToken(
        token=token_str, 
        trip_ids=ids_str, 
        title=title, 
        description=description, 
        expires_at=expires_at,
        user_id=current_user.id
    )
    db.session.add(new_token)
    db.session.commit()
    
    # Build public URL
    public_base = current_app.config.get('PUBLIC_BASE_URL')
    if public_base:
        path = url_for('main.shared_view', token=token_str, _external=False)
        share_url = urljoin(public_base.rstrip('/') + '/', path.lstrip('/'))
    else:
        share_url = url_for('main.shared_view', token=token_str, _external=True)
    flash(_('Sharing link created! URL: {url}').format(url=share_url))
    return redirect(url_for('main.profile'))

@main.route('/trip/mark-visited/<int:trip_id>', methods=['POST'])
@login_required
def mark_visited(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner != current_user:
        abort(403)
    
    end_date_str = request.form.get('end_date')
    if not end_date_str:
        flash(_('End date is required to mark as visited!'))
        return redirect(url_for('main.profile'))
    
    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        if end_date > datetime.now().date():
            flash(_('Visited trip end date cannot be in the future!'))
            return redirect(url_for('main.profile'))
            
        trip.end_date = end_date
        trip.status = 'visited'
        db.session.commit()
        # Award badges after interaction
        evaluate_user_badges(current_user)
        flash(_('Trip marked as visited! Awesome! Destination: {dest}').format(dest=trip.destination))
    except ValueError:
        flash(_('Invalid date format provided.'))
        
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
        return jsonify({'error': _('error_item_required')}), 400
        
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

@main.route('/shares')
@login_required
def shares_list():
    # Use user_id for filtering shares if available, otherwise fallback to old method
    user_shares_query = ShareToken.query.filter_by(user_id=current_user.id).all()
    
    # Fallback/Legacy: finding shares that contain user's trips but no user_id set
    user_trips_ids = [t.id for t in current_user.trips]
    if not user_shares_query:
        all_shares = ShareToken.query.filter(ShareToken.user_id == None).all()
        for share in all_shares:
            share_trip_ids = [int(tid) for tid in share.trip_ids.split(',')]
            if any(tid in user_trips_ids for tid in share_trip_ids):
                user_shares_query.append(share)

    user_shares_data = []
    for share in user_shares_query:
        share_trip_ids = [int(tid) for tid in share.trip_ids.split(',')]
        trips = Trip.query.filter(Trip.id.in_(share_trip_ids)).all()
        user_shares_data.append({
            'id': share.id,
            'token': share.token,
            'trip_ids': share.trip_ids,
            'trips': trips,
            'created_at': share.created_at,
            'title': share.title,
            'description': share.description,
            'expires_at': share.expires_at,
            'view_count': share.view_count
        })
            
    return render_template('shares.html', shares=user_shares_data, all_user_trips=current_user.trips)

@main.route('/share/edit/<int:share_id>', methods=['POST'])
@login_required
def edit_share(share_id):
    share = ShareToken.query.get_or_404(share_id)
    # Check ownership
    if share.user_id != current_user.id:
        share_trip_ids_orig = [int(tid) for tid in share.trip_ids.split(',')]
        user_trips_ids = [t.id for t in current_user.trips]
        if not any(tid in user_trips_ids for tid in share_trip_ids_orig):
            abort(403)
        
    new_trip_ids = request.form.getlist('trip_ids')
    if not new_trip_ids:
        flash('At least one trip must be selected.')
        return redirect(url_for('main.shares_list'))
        
    # Verify ownership of new trips
    for tid in new_trip_ids:
        trip = Trip.query.get(int(tid))
        if not trip or trip.owner != current_user:
            abort(403)
            
    share.trip_ids = ','.join(new_trip_ids)
    share.title = request.form.get('title')
    share.description = request.form.get('description')
    expires_at_str = request.form.get('expires_at')
    if expires_at_str:
        try:
            share.expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d')
        except ValueError:
            pass
    else:
        share.expires_at = None

    db.session.commit()
    flash('Shared link updated.')
    return redirect(url_for('main.shares_list'))

@main.route('/share/delete/<int:share_id>', methods=['POST'])
@login_required
def delete_share(share_id):
    share = ShareToken.query.get_or_404(share_id)
    # Check ownership (at least one trip must belong to user)
    share_trip_ids = [int(tid) for tid in share.trip_ids.split(',')]
    user_trips_ids = [t.id for t in current_user.trips]
    if not any(tid in user_trips_ids for tid in share_trip_ids):
        abort(403)
        
    db.session.delete(share)
    db.session.commit()
    flash(_('Sharing link deleted successfully!'))
    return redirect(url_for('main.shares_list'))

@main.route('/shared/<token>')
def shared_view(token):
    share_token = ShareToken.query.filter_by(token=token).first_or_404()
    
    # Check for expiration
    if share_token.expires_at and share_token.expires_at < datetime.utcnow():
        abort(410) # Gone / Expired
        
    # Increment view counts
    share_token.view_count += 1
    
    # Track unique views using session
    viewed_shares = session.get('viewed_shares', [])
    if token not in viewed_shares:
        share_token.unique_view_count += 1
        if isinstance(viewed_shares, list):
            viewed_shares.append(token)
        else:
            viewed_shares = [token]
        session['viewed_shares'] = viewed_shares
        
    db.session.commit()
    
    trip_ids = [int(tid) for tid in share_token.trip_ids.split(',')]
    trips = Trip.query.filter(Trip.id.in_(trip_ids)).all()
    # Sort shared trips by start_date
    trips = sorted(trips, key=lambda x: (x.start_date is None, x.start_date))
    
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
            'packing_list': trip.packing_list,
            'expense_estimate': trip.expense_estimate,
            'checklist': checklist_data
        })
    
    share_metadata = {
        'title': share_token.title,
        'description': share_token.description,
        'created_at': share_token.created_at,
        'view_count': share_token.view_count,
        'unique_view_count': share_token.unique_view_count
    }
    
    return render_template('shared_trip.html', trips=shared_trips_data, share=share_metadata)

@main.route('/calendar')
@login_required
def calendar():
    events = []
    for trip in current_user.trips:
        if trip.start_date:
            color = '#0d6efd' # primary
            if trip.status == 'visited':
                color = '#198754' # success
            elif trip.status == 'planned':
                color = '#ffc107' # warning
                
            events.append({
                'title': f"✈️ {trip.destination}, {trip.country}",
                'start': trip.start_date.isoformat(),
                'end': (trip.end_date.isoformat() if trip.end_date else trip.start_date.isoformat()),
                'url': url_for('main.edit_trip', trip_id=trip.id),
                'backgroundColor': color,
                'borderColor': color,
                'extendedProps': {
                    'status': trip.status,
                    'destination': trip.destination
                }
            })
    return render_template('calendar.html', events=events)
