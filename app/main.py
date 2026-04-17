import json
import os
import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app, session, Response, stream_with_context
from flask_babel import _, get_locale
from flask_login import login_required, current_user
from .models import Trip, ShareToken, TripChecklist, Badge, UserBadge, User, TripTransportSegment
from . import db
from datetime import datetime, timedelta, date
from country_list import countries_for_language
from urllib.parse import urljoin
from urllib.parse import quote
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.exc import IntegrityError

from .services.immich_service import ImmichService, ImmichError, ImmichNotConfigured, ImmichNotFound


main = Blueprint('main', __name__)

SUPPORTED_CURRENCIES = ('USD', 'EUR', 'GBP', 'HUF', 'CHF', 'JPY')
TRANSPORT_SEGMENT_KEYS = ('outbound', 'intercity', 'local')
TRANSPORT_SEGMENT_TYPES = ('outbound', 'arrival', 'return', 'intercity', 'local', 'other')
TRANSPORT_MODE_SUGGESTIONS = ('Flight', 'Train', 'Bus', 'Car', 'Ferry', 'Metro', 'Bike', 'Walk', 'Taxi')
SUPPORTED_LANGUAGES = ('en', 'hu')
SUPPORTED_LANDING_PAGES = {
    'profile': 'main.profile',
    'calendar': 'main.calendar',
    'stats': 'main.stats',
    'shares': 'main.shares_list',
}


def _get_user_landing_endpoint(user):
    landing_page = (getattr(user, 'preferred_landing_page', '') or 'profile').strip().lower()
    return SUPPORTED_LANDING_PAGES.get(landing_page, 'main.profile')


def _collect_transport_segments_from_form(form):
    # New dynamic list-style transport editor (preferred).
    modes = form.getlist('transport_mode[]')
    if modes:
        seg_types = form.getlist('transport_segment_type[]')
        labels = form.getlist('transport_label[]')
        refs = form.getlist('transport_reference_code[]')
        carriers = form.getlist('transport_carrier[]')
        ticket_refs = form.getlist('transport_ticket_ref[]')
        document_refs = form.getlist('transport_document_ref[]')
        visibilities = form.getlist('transport_visibility[]')

        segments = []
        for idx, mode_raw in enumerate(modes):
            mode = (mode_raw or '').strip()
            if not mode:
                continue

            seg_type = (seg_types[idx] if idx < len(seg_types) else 'other').strip().lower() or 'other'
            if seg_type not in TRANSPORT_SEGMENT_TYPES:
                seg_type = 'other'

            visibility = (visibilities[idx] if idx < len(visibilities) else 'private').strip().lower()
            segments.append({
                'segment_type': seg_type,
                'label': (labels[idx] if idx < len(labels) else '').strip() or None,
                'mode': mode,
                'reference_code': (refs[idx] if idx < len(refs) else '').strip() or None,
                'carrier': (carriers[idx] if idx < len(carriers) else '').strip() or None,
                'ticket_ref': (ticket_refs[idx] if idx < len(ticket_refs) else '').strip() or None,
                'document_ref': (document_refs[idx] if idx < len(document_refs) else '').strip() or None,
                'is_sensitive': visibility != 'public',
            })
        return segments

    # Legacy fixed fields (kept for compatibility with older forms).
    segments = []
    for seg_type in TRANSPORT_SEGMENT_KEYS:
        mode = (form.get(f'{seg_type}_transport_mode') or '').strip()
        ref = (form.get(f'{seg_type}_transport_ref') or '').strip()
        if not mode:
            continue
        segments.append({
            'segment_type': seg_type,
            'label': None,
            'mode': mode,
            'reference_code': ref or None,
            'carrier': None,
            'ticket_ref': None,
            'document_ref': None,
            'is_sensitive': seg_type != 'outbound',
        })
    return segments


def _sync_trip_transport_segments(trip, segments):
    trip.transport_segments.clear()
    for idx, segment in enumerate(segments):
        trip.transport_segments.append(TripTransportSegment(
            segment_type=segment.get('segment_type') or 'other',
            label=segment.get('label'),
            mode=segment['mode'],
            reference_code=segment.get('reference_code'),
            carrier=segment.get('carrier'),
            ticket_ref=segment.get('ticket_ref'),
            document_ref=segment.get('document_ref'),
            is_sensitive=bool(segment.get('is_sensitive', True)),
            order_index=idx,
        ))

    # Keep legacy fields in sync for compatibility (uses outbound leg only).
    outbound = next((s for s in segments if s.get('segment_type') == 'outbound'), None)
    if not outbound and segments:
        outbound = segments[0]
    trip.transport_mode = outbound['mode'] if outbound else None
    trip.flight_number = outbound.get('reference_code') if outbound else None


def _normalize_album_id(value):
    if value is None:
        return None
    clean = str(value).strip()
    return clean or None


def _normalize_currency(value, fallback='USD'):
    code = (value or '').strip().upper()
    return code if code in SUPPORTED_CURRENCIES else fallback


def _immich_signer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='immich-thumb')


def _is_trip_shared_with_token(trip_id, share_token_value):
    if not share_token_value:
        return False
    token = ShareToken.query.filter_by(token=share_token_value).first()
    if not token:
        return False
    if token.expires_at and token.expires_at < datetime.utcnow():
        return False

    trip_ids = {int(tid) for tid in token.trip_ids.split(',') if tid.strip().isdigit()}
    return trip_id in trip_ids


def _can_access_trip(trip, share_token_value=None):
    if current_user.is_authenticated and trip.user_id == current_user.id:
        return True
    return _is_trip_shared_with_token(trip.id, share_token_value)


def _ensure_user_immich_defaults(user):
    changed = False
    if not user.immich_base_url:
        default_url = current_app.config.get('IMMICH_BASE_URL')
        if default_url:
            user.immich_base_url = default_url
            changed = True
    if not user.immich_api_key:
        default_key = current_app.config.get('IMMICH_API_KEY')
        if default_key:
            user.immich_api_key = default_key
            changed = True
    if changed:
        db.session.commit()


def _immich_service_for_user(user):
    timeout = current_app.config.get('IMMICH_TIMEOUT', 10)
    retries = current_app.config.get('IMMICH_RETRY_COUNT', 2)
    return ImmichService.from_user(user, timeout=timeout, retries=retries)


def _settings_services_status(user):
    immich_ready = bool((user.immich_base_url or '').strip() and (user.immich_api_key or '').strip())
    return [
        {
            'id': 'immich',
            'name': 'Immich',
            'configured': immich_ready,
            'status_label': _('Configured') if immich_ready else _('Missing setup'),
            'description': _('Photo and video gallery integration for trips.'),
            'test_url': url_for('main.test_immich_service'),
        },
    ]


def _avatar_url_for_user(user):
    display_name = ((getattr(user, 'name', '') or '').strip() if user else '') or 'Nomad User'
    initials = ''.join(part[:1] for part in display_name.split()[:2]).upper() or 'N'
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 96 96'>"
        "<rect width='96' height='96' rx='48' fill='#3584e4'/>"
        f"<text x='48' y='56' text-anchor='middle' font-size='34' fill='white' "
        "font-family='Arial, sans-serif' font-weight='700'>"
        f"{initials}</text></svg>"
    )
    return f"data:image/svg+xml;utf8,{quote(svg)}"

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
    countries_en = list(countries_for_language('en'))
    code_by_en_name = {name.lower(): code for code, name in countries_en}

    def get_country_code(country_name):
        if not country_name:
            return None
        # Try to find the code for the given English name
        code = code_by_en_name.get(country_name.lower())
        return code.lower() if code else None

    def localize_country(country_name):
        if not country_name:
            return ''

        code = code_by_en_name.get(country_name.lower())
        if not code:
            return country_name

        lang = str(get_locale() or 'en').split('_')[0]
        try:
            localized = dict(countries_for_language(lang)).get(code)
            return localized or country_name
        except Exception:
            return country_name

    return dict(
        app_version=get_version(),
        get_country_code=get_country_code,
        localize_country=localize_country,
        avatar_url_for=_avatar_url_for_user,
    )

def get_countries():
    # country_list provides tuple (iso_code, name)
    # We'll use names for our application as requested before
    return sorted([name for code, name in countries_for_language('en')])

@main.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for(_get_user_landing_endpoint(current_user)))
    return render_template('index.html')

@main.route('/set_language/<lang>')
def set_language(lang):
    if lang in SUPPORTED_LANGUAGES:
        session['lang'] = lang
        if current_user.is_authenticated and current_user.preferred_language != lang:
            current_user.preferred_language = lang
            db.session.commit()
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

    def _normalize_mode(raw_mode):
        mode = (raw_mode or '').strip().lower()
        alias = {
            'flight': 'plane',
            'airplane': 'plane',
            'aeroplane': 'plane',
            'train': 'train',
            'car': 'car',
            'bus': 'bus',
            'ferry': 'ferry',
            'metro': 'metro',
            'bike': 'bike',
            'walk': 'walking',
            'taxi': 'taxi',
            'plane': 'plane',
        }
        return alias.get(mode, mode)

    trips = user.trips
    visited_countries = set([t.country for t in trips if t.status == 'visited'])
    visited_trips = [t for t in trips if t.status == 'visited']
    visited_transport_modes = [
        _normalize_mode(getattr(t, 'transport_mode', None))
        for t in visited_trips
        if getattr(t, 'transport_mode', None)
    ]
    visited_by_transport = {
        'plane': sum(1 for m in visited_transport_modes if m == 'plane'),
        'train': sum(1 for m in visited_transport_modes if m == 'train'),
        'car': sum(1 for m in visited_transport_modes if m == 'car'),
        'bus': sum(1 for m in visited_transport_modes if m == 'bus'),
        'ferry': sum(1 for m in visited_transport_modes if m == 'ferry'),
    }
    share_count = len(getattr(user, 'share_tokens', []) or [])
    
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
                'any': any,
                'all': all,
                'set': set,
                'sum': sum,
                'user': user,
                'trips': trips,
                'visited_countries': visited_countries,
                'eu_countries': eu_countries,
                'visited_eu': visited_eu,
                'visited_trips': visited_trips,
                'visited_transport_modes': visited_transport_modes,
                'visited_by_transport': visited_by_transport,
                'share_count': share_count,
                'africa_countries': africa_countries,
                'asia_countries': asia_countries,
                'americas_countries': americas_countries,
                'oceania_countries': oceania_countries,
                'visited_africa': visited_africa,
                'visited_asia': visited_asia,
                'visited_americas': visited_americas,
                'visited_oceania': visited_oceania
            }

            # Use globals context so comprehensions can resolve helper symbols (len/set/any/etc.).
            eval_globals = {'__builtins__': {}}
            eval_globals.update(eval_context)

            def safe_eval(expr):
                return eval(str(expr), eval_globals, {})
            
            for b_def in badge_defs:
                code = b_def.get('code')
                criteria = b_def.get('criteria')
                progress_expr = b_def.get('progress')
                
                if code and criteria:
                    try:
                        # Evaluate if awarded
                        if safe_eval(criteria):
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
                            progress = safe_eval(progress_expr)
                        elif code in awarded_codes:
                            progress = 100
                        
                        if current_expr:
                            current_val = safe_eval(current_expr)
                        elif code in awarded_codes:
                            current_val = 1 # Fallback
                        
                        if target_expr:
                            if isinstance(target_expr, (int, float)):
                                target_val = target_expr
                            else:
                                target_val = safe_eval(target_expr)
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


@main.route('/settings/immich', methods=['POST'])
@login_required
def save_immich_settings():
    current_user.immich_base_url = request.form.get('immich_base_url', '').strip() or None
    submitted_api_key = request.form.get('immich_api_key', '').strip()
    # Keep existing key if the field is intentionally left empty.
    if submitted_api_key:
        current_user.immich_api_key = submitted_api_key

    if request.form.get('clear_immich_api_key'):
        current_user.immich_api_key = None

    db.session.commit()
    flash(_('Immich settings saved.'))
    return redirect(url_for('main.settings'))


@main.route('/settings')
@login_required
def settings():
    _ensure_user_immich_defaults(current_user)
    pref_status = session.get('default_trip_status', 'planned')
    if pref_status not in {'draft', 'planned', 'visited'}:
        pref_status = 'planned'

    pref_transport = session.get('default_transport_mode', '')
    if pref_transport not in {'', 'Flight', 'Train', 'Bus', 'Car', 'Ferry'}:
        pref_transport = ''

    pref_language = (current_user.preferred_language or session.get('lang') or 'en').strip().lower()
    if pref_language not in SUPPORTED_LANGUAGES:
        pref_language = 'en'

    pref_landing_page = (current_user.preferred_landing_page or 'profile').strip().lower()
    if pref_landing_page not in SUPPORTED_LANDING_PAGES:
        pref_landing_page = 'profile'

    pref_week_start = (session.get('pref_week_start') or 'mon').strip().lower()
    if pref_week_start not in {'mon', 'sun'}:
        pref_week_start = 'mon'

    pref_date_format = (session.get('pref_date_format') or 'iso').strip().lower()
    if pref_date_format not in {'iso', 'eu', 'us'}:
        pref_date_format = 'iso'

    pref_distance_unit = (session.get('pref_distance_unit') or 'metric').strip().lower()
    if pref_distance_unit not in {'metric', 'imperial'}:
        pref_distance_unit = 'metric'

    pref_share_expiry_days = str(session.get('pref_share_expiry_days', '30')).strip()
    if pref_share_expiry_days not in {'0', '7', '30', '90'}:
        pref_share_expiry_days = '30'

    pref_planning_horizon_days = str(session.get('pref_planning_horizon_days', '180')).strip()
    if pref_planning_horizon_days not in {'30', '60', '90', '180', '365'}:
        pref_planning_horizon_days = '180'

    pref_home_country = (session.get('pref_home_country') or '').strip()
    countries = get_countries()
    if pref_home_country and pref_home_country not in countries:
        pref_home_country = ''

    pref_private_notes = bool(session.get('pref_private_notes', True))
    pref_hide_sensitive_transport = bool(session.get('pref_hide_sensitive_transport', True))
    pref_auto_archive_visited = bool(session.get('pref_auto_archive_visited', False))

    return render_template(
        'settings.html',
        currencies=SUPPORTED_CURRENCIES,
        countries=countries,
        pref_status=pref_status,
        pref_transport=pref_transport,
        pref_language=pref_language,
        pref_landing_page=pref_landing_page,
        pref_compact_mode=bool(current_user.compact_mode),
        pref_show_badge_toasts=bool(current_user.show_badge_toasts),
        pref_week_start=pref_week_start,
        pref_date_format=pref_date_format,
        pref_distance_unit=pref_distance_unit,
        pref_share_expiry_days=pref_share_expiry_days,
        pref_planning_horizon_days=pref_planning_horizon_days,
        pref_home_country=pref_home_country,
        pref_private_notes=pref_private_notes,
        pref_hide_sensitive_transport=pref_hide_sensitive_transport,
        pref_auto_archive_visited=pref_auto_archive_visited,
        services_status=_settings_services_status(current_user),
    )


@main.route('/settings/services/immich/test', methods=['POST'])
@login_required
def test_immich_service():
    try:
        service = _immich_service_for_user(current_user)
        ok, message = service.test_connection()
        return jsonify({'ok': bool(ok), 'message': message})
    except ImmichNotConfigured:
        return jsonify({'ok': False, 'message': _('Immich is not configured yet.')}), 400
    except ImmichError as exc:
        current_app.logger.warning(f"Immich test failed for user {current_user.id}: {exc}")
        return jsonify({'ok': False, 'message': _('Connection failed. Check URL/API key and server availability.')}), 502
    except Exception as exc:
        current_app.logger.error(f"Unexpected Immich test failure for user {current_user.id}: {exc}")
        return jsonify({'ok': False, 'message': _('Unexpected test error.')}), 500


@main.route('/settings/preferences', methods=['POST'])
@login_required
def save_preferences_settings():
    default_status = (request.form.get('default_trip_status') or 'planned').strip().lower()
    default_transport = (request.form.get('default_transport_mode') or '').strip()
    preferred_language = (request.form.get('preferred_language') or 'en').strip().lower()
    preferred_landing_page = (request.form.get('preferred_landing_page') or 'profile').strip().lower()
    compact_mode = bool(request.form.get('compact_mode'))
    show_badge_toasts = not bool(request.form.get('disable_badge_toasts'))
    week_start = (request.form.get('week_start') or 'mon').strip().lower()
    date_format = (request.form.get('date_format') or 'iso').strip().lower()
    distance_unit = (request.form.get('distance_unit') or 'metric').strip().lower()
    share_expiry_days = (request.form.get('share_expiry_days') or '30').strip()
    planning_horizon_days = (request.form.get('planning_horizon_days') or '180').strip()
    home_country = (request.form.get('home_country') or '').strip()
    private_notes = bool(request.form.get('private_notes'))
    hide_sensitive_transport = bool(request.form.get('hide_sensitive_transport'))
    auto_archive_visited = bool(request.form.get('auto_archive_visited'))

    allowed_statuses = {'draft', 'planned', 'visited'}
    if default_status not in allowed_statuses:
        default_status = 'planned'

    allowed_transport = {'', 'Flight', 'Train', 'Bus', 'Car', 'Ferry'}
    if default_transport not in allowed_transport:
        default_transport = ''

    if preferred_language not in SUPPORTED_LANGUAGES:
        preferred_language = 'en'

    if preferred_landing_page not in SUPPORTED_LANDING_PAGES:
        preferred_landing_page = 'profile'

    if week_start not in {'mon', 'sun'}:
        week_start = 'mon'

    if date_format not in {'iso', 'eu', 'us'}:
        date_format = 'iso'

    if distance_unit not in {'metric', 'imperial'}:
        distance_unit = 'metric'

    if share_expiry_days not in {'0', '7', '30', '90'}:
        share_expiry_days = '30'

    if planning_horizon_days not in {'30', '60', '90', '180', '365'}:
        planning_horizon_days = '180'

    countries = set(get_countries())
    if home_country not in countries:
        home_country = ''

    default_currency = _normalize_currency(
        request.form.get('default_currency'),
        fallback=(current_user.default_currency or current_app.config.get('DEFAULT_CURRENCY', 'USD')),
    )

    session['default_trip_status'] = default_status
    session['default_transport_mode'] = default_transport
    session['lang'] = preferred_language
    session['compact_mode'] = compact_mode
    session['show_badge_toasts'] = show_badge_toasts
    session['pref_week_start'] = week_start
    session['pref_date_format'] = date_format
    session['pref_distance_unit'] = distance_unit
    session['pref_share_expiry_days'] = share_expiry_days
    session['pref_planning_horizon_days'] = planning_horizon_days
    session['pref_home_country'] = home_country
    session['pref_private_notes'] = private_notes
    session['pref_hide_sensitive_transport'] = hide_sensitive_transport
    session['pref_auto_archive_visited'] = auto_archive_visited

    current_user.preferred_language = preferred_language
    current_user.preferred_landing_page = preferred_landing_page
    current_user.compact_mode = compact_mode
    current_user.show_badge_toasts = show_badge_toasts
    current_user.default_currency = default_currency
    db.session.commit()
    flash(_('Preferences saved.'))
    return redirect(url_for('main.settings'))


@main.route('/settings/account', methods=['POST'])
@login_required
def save_account_settings():
    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()

    if not name or not email:
        flash(_('Name and email are required.'))
        return redirect(url_for('main.settings'))

    existing = User.query.filter(User.email == email, User.id != current_user.id).first()
    if existing:
        flash(_('This email is already used by another account.'))
        return redirect(url_for('main.settings'))

    current_user.name = name
    current_user.email = email
    db.session.commit()
    flash(_('Account settings saved.'))
    return redirect(url_for('main.settings'))


@main.route('/settings/password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password') or ''
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    if not current_password or not new_password or not confirm_password:
        flash(_('Please fill all password fields.'))
        return redirect(url_for('main.settings'))

    if not current_user.check_password(current_password):
        flash(_('Current password is incorrect.'))
        return redirect(url_for('main.settings'))

    if len(new_password) < 8:
        flash(_('New password must be at least 8 characters long.'))
        return redirect(url_for('main.settings'))

    if new_password != confirm_password:
        flash(_('New password and confirmation do not match.'))
        return redirect(url_for('main.settings'))

    if current_password == new_password:
        flash(_('New password must be different from current password.'))
        return redirect(url_for('main.settings'))

    current_user.set_password(new_password)
    db.session.commit()
    flash(_('Password changed successfully.'))
    return redirect(url_for('main.settings'))

@main.route('/profile')
@login_required
def profile():
    _ensure_user_immich_defaults(current_user)
    # Evaluate badges on profile view (initial or refresh)
    badge_data = evaluate_user_badges(current_user)

    # Collect one-time toast events so the UI can explain exactly what changed.
    badge_toasts = []

    for b in badge_data:
        if not b.get('is_new'):
            continue
        progress_pct = int(round(float(b.get('progress') or 0)))
        current_val = b.get('current')
        target_val = b.get('target')
        badge_title = _(b.get('title') or 'Achievement')

        if current_val is not None and target_val not in (None, 0, '0'):
            message = _('%(badge)s - %(current)s/%(target)s (%(progress)s%%)',
                        badge=badge_title, current=current_val, target=target_val, progress=progress_pct)
        else:
            message = _('%(badge)s - %(progress)s%% completed', badge=badge_title, progress=progress_pct)

        badge_toasts.append({
            'icon': b.get('icon') or '🏆',
            'title': _('Achievement Progress!'),
            'message': message,
        })

    if not bool(current_user.show_badge_toasts):
        badge_toasts = []

    # Mark new badges as not new anymore after we've passed them to template.
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
                           badge_toasts=badge_toasts,
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
    def safe_float(value):
        try:
            if value is None:
                return None
            if isinstance(value, str):
                value = value.strip().replace(',', '.')
            return float(value)
        except (TypeError, ValueError):
            return None

    def coerce_date(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            raw = value.strip()
            for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y'):
                try:
                    return datetime.strptime(raw, fmt).date()
                except ValueError:
                    continue
        return None

    def safe_mode(raw_mode):
        if not raw_mode:
            return None
        mode = str(raw_mode).strip().lower()
        alias = {
            'flight': 'plane',
            'airplane': 'plane',
            'aeroplane': 'plane',
            'walk': 'walking',
        }
        return alias.get(mode, mode)

    try:
        trips = list(current_user.trips)
    except Exception as e:
        current_app.logger.error(f"Failed to load trips for stats page: {e}")
        return render_template('stats.html', stats={
            'visited_count': 0,
            'world_total': 0,
            'visited_percent': 0,
            'unvisited_count': 0,
            'total_trips': 0,
            'total_visited': 0,
            'total_planned': 0,
            'total_days_traveled': 0,
            'avg_trip_length': 0,
            'total_budget': 0,
            'avg_budget': 0,
            'avg_budget_per_day': 0,
            'monthly_data': {'labels': [], 'values': [], 'zipped': []},
            'top_transport': [],
            'top_countries': [],
            'longest_trip': None,
            'longest_trip_days': None,
            'shortest_trip': None,
            'shortest_trip_days': None,
            'trips_by_year': [],
            'next_trip_in_days': None,
            'longest_gap_days': 0,
            'avg_trips_per_year': 0,
        })

    today = datetime.now().date()

    def normalized_status(raw_status):
        if raw_status is None:
            return ''
        return str(raw_status).strip().lower()

    visited_trips = [t for t in trips if normalized_status(t.status) == 'visited']
    planned_trips = [t for t in trips if normalized_status(t.status) == 'planned']

    stats_data = {
        'visited_count': 0,
        'world_total': 0,
        'visited_percent': 0,
        'unvisited_count': 0,
        'total_trips': len(trips),
        'total_visited': len(visited_trips),
        'total_planned': len(planned_trips),
        'total_days_traveled': 0,
        'avg_trip_length': 0,
        'total_budget': 0,
        'avg_budget': 0,
        'avg_budget_per_day': 0,
        'monthly_data': {'labels': [], 'values': [], 'zipped': []},
        'top_transport': [],
        'top_countries': [],
        'longest_trip': None,
        'longest_trip_days': None,
        'shortest_trip': None,
        'shortest_trip_days': None,
        'trips_by_year': [],
        'next_trip_in_days': None,
        'longest_gap_days': 0,
        'avg_trips_per_year': 0,
    }

    visited_countries = {str(t.country).strip() for t in visited_trips if t.country}
    try:
        world_countries_count = len(list(countries_for_language('en')))
    except Exception as e:
        current_app.logger.warning(f"Could not load world country list for stats: {e}")
        world_countries_count = len(visited_countries)

    stats_data['visited_count'] = len(visited_countries)
    stats_data['world_total'] = world_countries_count
    stats_data['visited_percent'] = round((len(visited_countries) / world_countries_count) * 100, 1) if world_countries_count > 0 else 0
    stats_data['unvisited_count'] = max(0, world_countries_count - len(visited_countries))

    try:
        total_budget = 0.0
        trips_by_year = {}
        longest_trip = None
        shortest_trip = None
        max_duration = -1
        min_duration = 99999
        monthly_stats = {}
        total_duration = 0
        countries_by_trips = {}
        transport_counts = {}
        visited_dates = []

        for t in visited_trips:
            start_date = coerce_date(getattr(t, 'start_date', None))
            end_date = coerce_date(getattr(t, 'end_date', None))

            if start_date:
                trips_by_year[start_date.year] = trips_by_year.get(start_date.year, 0) + 1
                month_key = start_date.strftime('%Y-%m')
                monthly_stats[month_key] = monthly_stats.get(month_key, 0) + 1

            if t.country:
                country_key = str(t.country).strip()
                countries_by_trips[country_key] = countries_by_trips.get(country_key, 0) + 1

            budget_val = safe_float(t.budget)
            if budget_val is not None:
                total_budget += budget_val

            if start_date and end_date:
                duration = (end_date - start_date).days
                if duration < 0:
                    continue
                if duration > max_duration:
                    max_duration = duration
                    longest_trip = t
                if duration < min_duration:
                    min_duration = duration
                    shortest_trip = t
                if duration > 0:
                    total_duration += duration

            if end_date:
                visited_dates.append(end_date)
            elif start_date:
                visited_dates.append(start_date)

            mode = safe_mode(getattr(t, 'transport_mode', getattr(t, 'transport', None)))
            if mode:
                transport_counts[mode] = transport_counts.get(mode, 0) + 1

        sorted_months = sorted(monthly_stats.keys())
        month_labels = [datetime.strptime(m, '%Y-%m').strftime('%b %y') for m in sorted_months]
        month_values = [monthly_stats[m] for m in sorted_months]
        monthly_data = {
            'labels': month_labels,
            'values': month_values,
            'zipped': list(zip(month_labels, month_values)),
        }

        sorted_transport = sorted(transport_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_countries = sorted(countries_by_trips.items(), key=lambda x: x[1], reverse=True)[:5]
        longest_trip_days = max_duration if max_duration >= 0 else None
        shortest_trip_days = min_duration if min_duration != 99999 else None

        next_planned_dates = sorted([
            d for d in (coerce_date(getattr(t, 'start_date', None)) for t in planned_trips)
            if d and d >= today
        ])
        next_trip_in_days = (next_planned_dates[0] - today).days if next_planned_dates else None

        visited_dates = sorted(set(visited_dates))
        longest_gap_days = 0
        if len(visited_dates) > 1:
            for i in range(1, len(visited_dates)):
                gap = (visited_dates[i] - visited_dates[i - 1]).days
                if gap > longest_gap_days:
                    longest_gap_days = gap

        avg_trips_per_year = round(sum(trips_by_year.values()) / len(trips_by_year), 1) if trips_by_year else 0

        stats_data.update({
            'total_days_traveled': total_duration,
            'avg_trip_length': round(total_duration / len(visited_trips), 1) if visited_trips else 0,
            'total_budget': round(total_budget, 2),
            'avg_budget': round(total_budget / len(visited_trips), 2) if visited_trips else 0,
            'avg_budget_per_day': round(total_budget / total_duration, 2) if total_duration > 0 else 0,
            'monthly_data': monthly_data,
            'top_transport': sorted_transport,
            'top_countries': top_countries,
            'longest_trip': longest_trip,
            'longest_trip_days': longest_trip_days,
            'shortest_trip': shortest_trip,
            'shortest_trip_days': shortest_trip_days,
            'trips_by_year': sorted(trips_by_year.items(), reverse=True),
            'next_trip_in_days': next_trip_in_days,
            'longest_gap_days': longest_gap_days,
            'avg_trips_per_year': avg_trips_per_year,
        })
    except Exception as e:
        current_app.logger.error(f"Failed to calculate advanced stats metrics: {e}")

    return render_template('stats.html', stats=stats_data)


@main.route('/stat')
@login_required
def stat_redirect():
    return redirect(url_for('main.stats'))

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
        currency = _normalize_currency(
            request.form.get('currency'),
            fallback=(current_user.default_currency or current_app.config.get('DEFAULT_CURRENCY', 'USD')),
        )
        accommodation = request.form.get('accommodation')
        attractions = request.form.get('attractions')
        notes = request.form.get('notes')
        
        transport_segments = _collect_transport_segments_from_form(request.form)
        packing_list = request.form.get('packing_list')
        expense_estimate = request.form.get('expense_estimate')
        visa_required = True if request.form.get('visa_required') else False
        immich_album_id = _normalize_album_id(request.form.get('immich_album_id'))

        new_trip = Trip(destination=destination, country=country, 
                        latitude=latitude, longitude=longitude,
                        start_date=start_date, end_date=end_date, 
                        status=status, budget=budget, currency=currency,
                        accommodation=accommodation, attractions=attractions, 
                        notes=notes, packing_list=packing_list,
                        expense_estimate=expense_estimate, visa_required=visa_required,
                        immich_album_id=immich_album_id,
                        owner=current_user)

        _sync_trip_transport_segments(new_trip, transport_segments)
        
        db.session.add(new_trip)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(_('This Immich album is already linked to another trip.'))
            return redirect(url_for('main.add_trip'))
        # Award badges after interaction
        evaluate_user_badges(current_user)
        flash(_('Trip added successfully!'))
        return redirect(url_for('main.profile'))

    countries = get_countries()
    pref_status = session.get('default_trip_status', 'planned')
    if pref_status not in {'draft', 'planned', 'visited'}:
        pref_status = 'planned'

    pref_transport = session.get('default_transport_mode', '')
    if pref_transport not in {'', 'Flight', 'Train', 'Bus', 'Car', 'Ferry'}:
        pref_transport = ''

    pref_currency = _normalize_currency(
        current_user.default_currency,
        fallback=current_app.config.get('DEFAULT_CURRENCY', 'USD'),
    )

    return render_template(
        'add_trip.html',
        countries=countries,
        pref_status=pref_status,
        pref_transport=pref_transport,
        pref_currency=pref_currency,
        currencies=SUPPORTED_CURRENCIES,
        transport_segment_types=TRANSPORT_SEGMENT_TYPES,
        transport_modes=TRANSPORT_MODE_SUGGESTIONS,
    )

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
        trip.currency = _normalize_currency(
            request.form.get('currency'),
            fallback=(current_user.default_currency or current_app.config.get('DEFAULT_CURRENCY', 'USD')),
        )
        trip.accommodation = request.form.get('accommodation')
        trip.attractions = request.form.get('attractions')
        trip.notes = request.form.get('notes')
        
        transport_segments = _collect_transport_segments_from_form(request.form)
        trip.packing_list = request.form.get('packing_list')
        trip.expense_estimate = request.form.get('expense_estimate')
        trip.visa_required = True if request.form.get('visa_required') else False
        trip.immich_album_id = _normalize_album_id(request.form.get('immich_album_id'))
        _sync_trip_transport_segments(trip, transport_segments)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(_('This Immich album is already linked to another trip.'))
            return redirect(url_for('main.edit_trip', trip_id=trip_id))
        flash(_('Trip updated successfully!'))
        return redirect(url_for('main.profile'))

    countries = get_countries()
    transport_segments_data = [
        {
            'segment_type': seg.segment_type or 'other',
            'label': seg.label or '',
            'mode': seg.mode or '',
            'reference_code': seg.reference_code or '',
            'carrier': seg.carrier or '',
            'ticket_ref': seg.ticket_ref or '',
            'document_ref': seg.document_ref or '',
            'visibility': 'private' if seg.is_sensitive else 'public',
        }
        for seg in sorted(trip.transport_segments, key=lambda s: (s.order_index, s.id))
    ]
    if not transport_segments_data and (trip.transport_mode or trip.flight_number):
        transport_segments_data.append({
            'segment_type': 'outbound',
            'label': '',
            'mode': trip.transport_mode or '',
            'reference_code': trip.flight_number or '',
            'carrier': '',
            'ticket_ref': '',
            'document_ref': '',
            'visibility': 'public',
        })

    return render_template(
        'edit_trip.html',
        trip=trip,
        countries=countries,
        currencies=SUPPORTED_CURRENCIES,
        transport_segment_types=TRANSPORT_SEGMENT_TYPES,
        transport_modes=TRANSPORT_MODE_SUGGESTIONS,
        transport_segments_data=transport_segments_data,
    )

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
            share_trip_ids = [int(tid) for tid in share.trip_ids.split(',') if tid.strip()]
            if any(tid in user_trips_ids for tid in share_trip_ids):
                user_shares_query.append(share)

    user_shares_data = []
    for share in user_shares_query:
        share_trip_ids = [int(tid) for tid in share.trip_ids.split(',') if tid.strip()]
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
            'view_count': share.view_count,
            'unique_view_count': share.unique_view_count
        })
            
    return render_template('shares.html', shares=user_shares_data, all_user_trips=current_user.trips)

@main.route('/share/edit/<int:share_id>', methods=['POST'])
@login_required
def edit_share(share_id):
    share = ShareToken.query.get_or_404(share_id)
    # Check ownership
    if share.user_id != current_user.id:
        share_trip_ids_orig = [int(tid) for tid in share.trip_ids.split(',') if tid.strip()]
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
    share_trip_ids = [int(tid) for tid in share.trip_ids.split(',') if tid.strip()]
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
    
    trip_ids = [int(tid) for tid in share_token.trip_ids.split(',') if tid.strip()]
    trips = Trip.query.filter(Trip.id.in_(trip_ids)).all()
    # Sort shared trips by start_date
    trips = sorted(trips, key=lambda x: (x.start_date is None, x.start_date))

    cities_preview_limit = 5
    journey_start = None
    journey_end = None
    journey_total_days = None
    highlights_count = sum(1 for trip in trips if bool((trip.attractions or '').strip()))
    gallery_count = sum(1 for trip in trips if bool((trip.immich_album_id or '').strip()))
    unique_cities = []
    unique_countries = []
    seen_city_keys = set()
    seen_country_keys = set()
    today = datetime.utcnow().date()

    for trip in trips:
        city = (trip.destination or '').strip()
        country = (trip.country or '').strip()
        city_key = (city.lower(), country.lower())
        country_key = country.lower()

        if city and city_key not in seen_city_keys:
            seen_city_keys.add(city_key)
            unique_cities.append({'destination': city, 'country': country})

        if country and country_key not in seen_country_keys:
            seen_country_keys.add(country_key)
            unique_countries.append(country)
    dated_starts = [trip.start_date for trip in trips if trip.start_date]
    dated_ends = [trip.end_date or trip.start_date for trip in trips if trip.start_date]
    if dated_starts and dated_ends:
        journey_start = min(dated_starts)
        journey_end = max(dated_ends)
        if journey_end >= journey_start:
            journey_total_days = (journey_end - journey_start).days + 1

    active_candidates = [
        trip for trip in trips
        if trip.start_date
        and trip.start_date <= today
        and (trip.end_date or trip.start_date) >= today
        and trip.status in ('planned', 'visited')
    ]
    active_candidates.sort(key=lambda t: t.start_date or date.min, reverse=True)
    active_trip = active_candidates[0] if active_candidates else None
    current_stop = None
    if active_trip:
        current_stop = {
            'destination': active_trip.destination,
            'country': active_trip.country,
            'start_date': active_trip.start_date,
            'end_date': active_trip.end_date,
        }
    
    shared_trips_data = []
    for trip in trips:
        ordered_segments = sorted(trip.transport_segments, key=lambda s: (s.order_index, s.id))
        public_segments = [seg for seg in ordered_segments if not seg.is_sensitive]
        outbound_segment = next((seg for seg in public_segments if seg.segment_type == 'outbound'), None)
        if not outbound_segment and public_segments:
            outbound_segment = public_segments[0]

        transport_hidden = False
        outbound_transport_mode = None
        if ordered_segments:
            if outbound_segment:
                outbound_transport_mode = outbound_segment.mode
            else:
                transport_hidden = True
        else:
            outbound_transport_mode = trip.transport_mode or None

        shared_trips_data.append({
            'id': trip.id,
            'destination': trip.destination,
            'country': trip.country,
            'start_date': trip.start_date,
            'end_date': trip.end_date,
            'attractions': trip.attractions,
            'trip_days': ((trip.end_date - trip.start_date).days + 1) if trip.start_date and trip.end_date and trip.end_date >= trip.start_date else None,
            'latitude': trip.latitude,
            'longitude': trip.longitude,
            'status': trip.status,
            'outbound_transport_mode': outbound_transport_mode,
            'transport_hidden': transport_hidden,
            'visa_required': trip.visa_required,
            'immich_album_id': trip.immich_album_id,
        })
    
    share_metadata = {
        'token': share_token.token,
        'title': share_token.title,
        'description': share_token.description,
        'created_at': share_token.created_at,
        'view_count': share_token.view_count,
        'unique_view_count': share_token.unique_view_count,
        'journey_start': journey_start,
        'journey_end': journey_end,
        'journey_total_days': journey_total_days,
        'city_count': len(unique_cities),
        'cities_list': unique_cities,
        'cities_preview': unique_cities[:cities_preview_limit],
        'cities_overflow_count': max(0, len(unique_cities) - cities_preview_limit),
        'countries_list': unique_countries,
        'country_count': len(unique_countries),
        'current_stop': current_stop,
        'highlights_count': highlights_count,
        'gallery_count': gallery_count,
    }
    
    return render_template('shared_trip.html', trips=shared_trips_data, share=share_metadata)


@main.route('/trip/<int:trip_id>')
@login_required
def trip_detail(trip_id):
    _ensure_user_immich_defaults(current_user)
    trip = Trip.query.get_or_404(trip_id)
    if trip.owner != current_user:
        abort(403)
    return render_template('trip_detail.html', trip=trip)


@main.route('/api/trips/<int:trip_id>/immich-gallery')
def get_trip_gallery(trip_id):
    trip = Trip.query.get_or_404(trip_id)
    share_token_value = request.args.get('share_token')
    if not _can_access_trip(trip, share_token_value):
        abort(403)

    if not trip.immich_album_id:
        return jsonify({'trip_id': trip.id, 'album': None, 'assets': []})

    try:
        service = _immich_service_for_user(trip.owner)
        album = service.get_album(trip.immich_album_id)
        assets = service.get_album_assets(trip.immich_album_id)
        signer = _immich_signer()

        normalized_assets = []
        for asset in assets:
            asset_id = asset.get('id')
            if not asset_id:
                continue
            sig = signer.dumps({'trip_id': trip.id, 'asset_id': asset_id})
            thumb_url = url_for(
                'main.immich_thumbnail_proxy',
                trip_id=trip.id,
                asset_id=asset_id,
                sig=sig,
                share_token=share_token_value,
                size='thumbnail',
            )
            preview_url = url_for(
                'main.immich_thumbnail_proxy',
                trip_id=trip.id,
                asset_id=asset_id,
                sig=sig,
                share_token=share_token_value,
                size='preview',
            )
            full_url = url_for(
                'main.immich_asset_proxy',
                trip_id=trip.id,
                asset_id=asset_id,
                sig=sig,
                share_token=share_token_value,
            )

            media_type = (asset.get('type') or asset.get('assetType') or '').lower()
            mime_type = (asset.get('originalMimeType') or asset.get('mimeType') or '').lower()
            is_video = media_type == 'video' or mime_type.startswith('video/')
            normalized_assets.append({
                'id': asset_id,
                'thumb_url': thumb_url,
                'preview_url': preview_url,
                'full_url': full_url,
                'media_type': 'video' if is_video else 'image',
                'created_at': asset.get('fileCreatedAt') or asset.get('createdAt'),
            })

        return jsonify({
            'trip_id': trip.id,
            'album': {
                'id': album.get('id', trip.immich_album_id),
                'name': album.get('albumName') or album.get('name') or trip.destination,
                'asset_count': len(normalized_assets),
            },
            'assets': normalized_assets,
        })
    except ImmichNotConfigured:
        return jsonify({'error': 'immich_not_configured'}), 503
    except ImmichNotFound:
        return jsonify({'error': 'album_not_found'}), 404
    except ImmichError as exc:
        current_app.logger.error(f"Immich gallery fetch failed for trip {trip.id}: {exc}")
        return jsonify({'error': 'immich_unavailable'}), 502


@main.route('/api/immich/thumb/<int:trip_id>/<asset_id>')
def immich_thumbnail_proxy(trip_id, asset_id):
    trip = Trip.query.get_or_404(trip_id)
    share_token_value = request.args.get('share_token')
    if not _can_access_trip(trip, share_token_value):
        abort(403)

    sig = request.args.get('sig')
    if not sig:
        abort(403)

    payload = None
    try:
        payload = _immich_signer().loads(sig)
    except BadSignature:
        abort(403)

    if not payload or payload.get('trip_id') != trip.id or payload.get('asset_id') != asset_id:
        abort(403)

    try:
        service = _immich_service_for_user(trip.owner)
        size = request.args.get('size', 'preview')
        upstream_response, content_type = service.get_thumbnail(asset_id, size=size)

        def generate():
            try:
                for chunk in upstream_response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                upstream_response.close()

        response = Response(stream_with_context(generate()), content_type=content_type)
        response.headers['Cache-Control'] = 'private, max-age=300'
        return response
    except ImmichNotFound:
        return jsonify({'error': 'asset_not_found'}), 404
    except ImmichError as exc:
        current_app.logger.error(f"Immich thumbnail proxy failed for trip {trip.id}, asset {asset_id}: {exc}")
        return jsonify({'error': 'immich_unavailable'}), 502


@main.route('/api/immich/asset/<int:trip_id>/<asset_id>')
def immich_asset_proxy(trip_id, asset_id):
    trip = Trip.query.get_or_404(trip_id)
    share_token_value = request.args.get('share_token')
    if not _can_access_trip(trip, share_token_value):
        abort(403)

    sig = request.args.get('sig')
    if not sig:
        abort(403)

    payload = None
    try:
        payload = _immich_signer().loads(sig)
    except BadSignature:
        abort(403)

    if not payload or payload.get('trip_id') != trip.id or payload.get('asset_id') != asset_id:
        abort(403)

    try:
        service = _immich_service_for_user(trip.owner)
        upstream_response, content_type = service.get_asset_binary(asset_id)

        def generate():
            try:
                for chunk in upstream_response.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
            finally:
                upstream_response.close()

        response = Response(stream_with_context(generate()), content_type=content_type)
        response.headers['Cache-Control'] = 'private, max-age=300'
        response.headers['Content-Disposition'] = 'inline'
        return response
    except ImmichNotFound:
        return jsonify({'error': 'asset_not_found'}), 404
    except ImmichError as exc:
        current_app.logger.error(f"Immich asset proxy failed for trip {trip.id}, asset {asset_id}: {exc}")
        return jsonify({'error': 'immich_unavailable'}), 502

@main.route('/calendar')
@login_required
def calendar():
    events = []
    undated_trips = []
    today = datetime.now().date()

    status_colors = {
        'visited': '#198754',
        'planned': '#ffc107',
        'draft': '#0d6efd',
    }

    for trip in current_user.trips:
        if not trip.start_date:
            undated_trips.append({
                'id': trip.id,
                'destination': trip.destination,
                'country': trip.country,
                'status': trip.status,
                'edit_url': url_for('main.edit_trip', trip_id=trip.id),
            })
            continue

        end_inclusive = trip.end_date or trip.start_date
        end_exclusive = end_inclusive + timedelta(days=1)
        color = status_colors.get(trip.status, '#0d6efd')
        days_until_start = (trip.start_date - today).days
        is_overdue = trip.status in ('planned', 'draft') and trip.start_date < today
        is_ongoing = trip.start_date <= today <= end_inclusive
        checklist_total = len(trip.checklist)
        checklist_done = sum(1 for item in trip.checklist if item.is_done)

        class_names = [f"trip-status-{trip.status}"]
        if is_overdue:
            class_names.append('trip-overdue')
        if is_ongoing:
            class_names.append('trip-ongoing')

        events.append({
            'id': str(trip.id),
            'title': f"{trip.destination}, {trip.country}",
            'start': trip.start_date.isoformat(),
            'end': end_exclusive.isoformat(),
            'allDay': True,
            'url': url_for('main.edit_trip', trip_id=trip.id),
            'backgroundColor': color,
            'borderColor': color,
            'classNames': class_names,
            'extendedProps': {
                'status': trip.status,
                'destination': trip.destination,
                'country': trip.country,
                'startDate': trip.start_date.isoformat(),
                'endDate': end_inclusive.isoformat(),
                'isOverdue': is_overdue,
                'isOngoing': is_ongoing,
                'daysUntilStart': days_until_start,
                'transportMode': trip.transport_mode,
                'flightNumber': trip.flight_number,
                'visaRequired': bool(trip.visa_required),
                'notes': trip.notes,
                'attractions': trip.attractions,
                'checklistDone': checklist_done,
                'checklistTotal': checklist_total,
                'editUrl': url_for('main.edit_trip', trip_id=trip.id),
                'markVisitedUrl': url_for('main.mark_visited', trip_id=trip.id),
            }
        })

    return render_template('calendar.html', events=events, undated_trips=undated_trips)
