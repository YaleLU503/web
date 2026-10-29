"""Station proximity to polygon boundaries, measured on a spherical Earth."""
import json
import math
from functools import lru_cache
from pathlib import Path

EARTH_KM = 6371.0088
LIMIT_KM = 2.0


@lru_cache(maxsize=1)
def station_data():
    data = json.loads(Path(__file__).with_name('railway_stations.geojson').read_text(encoding='utf-8'))
    if not data.get('features'):
        raise ValueError('Railway station dataset is empty.')
    return data


def vector(point):
    lon, lat = map(math.radians, point[:2])
    return (math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def angle(a, b):
    return math.atan2(math.sqrt(dot(cross(a, b), cross(a, b))), dot(a, b))


def segment_distance(p, a, b):
    """Shortest distance to a minor great-circle segment, including endpoints."""
    best = min(angle(p, a), angle(p, b))
    normal = cross(a, b)
    squared = dot(normal, normal)
    if squared < 1e-24:
        return best * EARTH_KM
    projection = tuple(p[i] - dot(p, normal)/squared*normal[i] for i in range(3))
    length = math.sqrt(dot(projection, projection))
    if length > 1e-12:
        q = tuple(x/length for x in projection)
        if angle(a, q) + angle(q, b) <= angle(a, b) + 1e-10:
            best = min(best, angle(p, q))
    return best * EARTH_KM


@lru_cache(maxsize=4096)
def station_near_boundary(geometry_json):
    geometry = json.loads(geometry_json)
    polygons = [geometry['coordinates']] if geometry.get('type') == 'Polygon' else geometry.get('coordinates', []) if geometry.get('type') == 'MultiPolygon' else []
    rings = [ring for polygon in polygons for ring in polygon if len(ring) >= 3]
    points = [p for ring in rings for p in ring]
    if not points:
        return None
    # Conservative bounding box prefilter for the project's UK geometries.
    south, north = min(p[1] for p in points), max(p[1] for p in points)
    west, east = min(p[0] for p in points), max(p[0] for p in points)
    lat_pad = math.degrees(LIMIT_KM / EARTH_KM) + 0.001
    lon_pad = lat_pad / max(0.01, math.cos(math.radians(max(abs(south), abs(north)) + lat_pad)))
    stations = [f for f in station_data()['features'] if f.get('geometry', {}).get('type') == 'Point' and west-lon_pad <= f['geometry']['coordinates'][0] <= east+lon_pad and south-lat_pad <= f['geometry']['coordinates'][1] <= north+lat_pad]
    segments = []
    for ring in rings:
        vertices = list(map(vector, ring))
        for i, (a, b) in enumerate(zip(vertices, vertices[1:] + vertices[:1])):
            start, end = ring[i], ring[(i+1) % len(ring)]
            # Extra angular margin bounds great-circle bulge as well as proximity.
            margin = math.degrees(angle(a, b)) + lon_pad + lat_pad
            segments.append((a, b, min(start[0],end[0])-margin, max(start[0],end[0])+margin, min(start[1],end[1])-margin, max(start[1],end[1])+margin))
    nearest, minimum = None, LIMIT_KM + 1e-9
    for station in stations:
        p = vector(station['geometry']['coordinates'])
        lon, lat = station['geometry']['coordinates'][:2]
        distance = min((segment_distance(p, a, b) for a, b, west, east, south, north in segments if west <= lon <= east and south <= lat <= north), default=math.inf)
        if distance <= minimum:
            minimum = distance
            props = station.get('properties', {})
            nearest = {'id': props.get('id'), 'name': props.get('name', 'Unnamed station'), 'coordinates': station['geometry']['coordinates'], 'boundary_distance_km': distance}
    return nearest


def nearest_station(geometry):
    return station_near_boundary(json.dumps(geometry or {}, separators=(',', ':')))
