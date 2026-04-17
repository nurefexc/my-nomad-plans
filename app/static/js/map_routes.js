(function () {
    function parseDateOnly(dateStr) {
        if (!dateStr || typeof dateStr !== 'string') return null;
        var parts = dateStr.split('-').map(Number);
        if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
        return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    }

    function getChronoDate(trip) {
        return parseDateOnly(trip.start_date) || parseDateOnly(trip.end_date);
    }

    function getDepartureDate(trip) {
        return parseDateOnly(trip.end_date) || parseDateOnly(trip.start_date);
    }

    function dayDiff(a, b) {
        var dayMs = 24 * 60 * 60 * 1000;
        return Math.round((b.getTime() - a.getTime()) / dayMs);
    }

    function lerpLatLng(from, to, ratio) {
        return [
            from[0] + (to[0] - from[0]) * ratio,
            from[1] + (to[1] - from[1]) * ratio,
        ];
    }

    function getAngleOnScreen(map, from, to) {
        var p1 = map.latLngToLayerPoint(L.latLng(from[0], from[1]));
        var p2 = map.latLngToLayerPoint(L.latLng(to[0], to[1]));
        return Math.atan2(p2.y - p1.y, p2.x - p1.x) * (180 / Math.PI);
    }

    function addArrowMarker(map, from, to, color) {
        if (from[0] === to[0] && from[1] === to[1]) return;
        var mid = lerpLatLng(from, to, 0.55);
        var angle = getAngleOnScreen(map, from, to);
        var icon = L.divIcon({
            className: 'map-arrow-icon',
            html: '<div class="map-arrow-glyph" style="border-left-color:' + color + '; transform: rotate(' + angle + 'deg);"></div>',
            iconSize: [22, 22],
            iconAnchor: [11, 11],
        });
        L.marker(mid, { icon: icon, interactive: false, keyboard: false }).addTo(map);
    }

    function renderMapStatsControl(map, stats) {
        var control = L.control({ position: 'topright' });
        control.onAdd = function () {
            var div = L.DomUtil.create('div', 'map-legend map-legend-compact');
            div.innerHTML =
                '<div class="map-legend-title">Map summary</div>' +
                '<div>Stops: <b>' + stats.stops + '</b></div>' +
                '<div>Routes: <b>' + stats.segments + '</b></div>';
            return div;
        };
        control.addTo(map);
    }

    function renderTripMap(mapId, trips, options) {
        if (!window.L) return null;

        var opts = Object.assign({
            connectWindowDays: 1,
            enableLayerControl: true,
            showLegend: true,
            showSummary: true,
            editable: false,
        }, options || {});

        var statusStyles = {
            visited: { color: '#6c757d', dashArray: '10, 10', label: 'Visited' },
            planned: { color: '#2ec4b6', dashArray: '1, 12', label: 'Planned' },
            draft: { color: '#3584e4', dashArray: '4, 10', label: 'Draft' },
        };

        var map = L.map(mapId).setView([20, 0], 2);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20,
        }).addTo(map);

        var grouped = { visited: [], planned: [], draft: [] };
        var markerLayers = { visited: L.layerGroup().addTo(map), planned: L.layerGroup().addTo(map), draft: L.layerGroup().addTo(map) };
        var routeLayers = { visited: L.layerGroup().addTo(map), planned: L.layerGroup().addTo(map), draft: L.layerGroup().addTo(map) };

        var bounds = [];
        var validStops = 0;
        var segmentCount = 0;

        (trips || []).forEach(function (trip) {
            if (trip.latitude === null || trip.longitude === null) return;
            var status = statusStyles[trip.status] ? trip.status : 'draft';
            var style = statusStyles[status];

            var marker = L.circleMarker([trip.latitude, trip.longitude], {
                radius: 8,
                fillColor: style.color,
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.9,
            });

            var popup = '<b>' + (trip.destination || 'Unknown') + '</b><br>' + (trip.country || '-') + '<br>Status: ' + style.label;
            if (opts.editable && trip.edit_url) {
                popup += '<br><a href="' + trip.edit_url + '" class="btn btn-sm btn-primary mt-2 py-1 px-3 text-white" style="font-size:0.7rem;">Edit</a>';
            }
            marker.bindPopup(popup);
            marker.addTo(markerLayers[status]);

            bounds.push([trip.latitude, trip.longitude]);
            grouped[status].push(trip);
            validStops += 1;
        });

        if (bounds.length === 1) {
            map.setView(bounds[0], 5);
        } else if (bounds.length > 1) {
            map.fitBounds(bounds, { padding: [20, 20] });
        }

        Object.keys(grouped).forEach(function (status) {
            var style = statusStyles[status];
            var sortedTrips = grouped[status].slice().sort(function (a, b) {
                var ad = getChronoDate(a);
                var bd = getChronoDate(b);
                if (!ad && !bd) return 0;
                if (!ad) return 1;
                if (!bd) return -1;
                return ad - bd;
            });

            for (var i = 0; i < sortedTrips.length - 1; i++) {
                var fromTrip = sortedTrips[i];
                var toTrip = sortedTrips[i + 1];
                var fromDate = getDepartureDate(fromTrip);
                var toDate = parseDateOnly(toTrip.start_date);
                if (!fromDate || !toDate) continue;

                var gapDays = dayDiff(fromDate, toDate);
                if (gapDays < 0 || gapDays > opts.connectWindowDays) continue;

                var from = [fromTrip.latitude, fromTrip.longitude];
                var to = [toTrip.latitude, toTrip.longitude];
                if (from[0] === to[0] && from[1] === to[1]) continue;

                L.polyline([from, to], {
                    color: style.color,
                    weight: 4,
                    dashArray: style.dashArray,
                    opacity: 0.75,
                    lineCap: 'round',
                }).addTo(routeLayers[status]);

                addArrowMarker(map, from, to, style.color);
                segmentCount += 1;
            }
        });

        if (opts.enableLayerControl) {
            L.control.layers({}, {
                'Visited markers': markerLayers.visited,
                'Planned markers': markerLayers.planned,
                'Draft markers': markerLayers.draft,
                'Visited routes': routeLayers.visited,
                'Planned routes': routeLayers.planned,
                'Draft routes': routeLayers.draft,
            }, { collapsed: true }).addTo(map);
        }

        if (opts.showLegend) {
            var legend = L.control({ position: 'bottomleft' });
            legend.onAdd = function () {
                var div = L.DomUtil.create('div', 'map-legend');
                div.innerHTML =
                    '<div class="map-legend-title">Route types</div>' +
                    '<div><span class="map-dot" style="background:#6c757d"></span>Visited</div>' +
                    '<div><span class="map-dot" style="background:#2ec4b6"></span>Planned</div>' +
                    '<div><span class="map-dot" style="background:#3584e4"></span>Draft</div>' +
                    '<small>Connections: same-day to +' + opts.connectWindowDays + ' day(s).</small>';
                return div;
            };
            legend.addTo(map);
        }

        if (opts.showSummary) {
            renderMapStatsControl(map, { stops: validStops, segments: segmentCount });
        }

        return map;
    }

    window.NomadMap = {
        renderTripMap: renderTripMap,
    };
})();

