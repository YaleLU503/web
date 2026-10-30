"""Local browser UI for the green-space recommendation demo.

Run: python recommendation_web_demo.py
Then open: http://127.0.0.1:8765
"""

import gzip
import argparse
import os
import json
import subprocess
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import recommend_demo
import station_filter


ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "web_demo_history.json"
CITIES = {
    "London": (51.5074, -0.1278), "Manchester": (53.4808, -2.2426),
    "Birmingham": (52.4862, -1.8904), "Edinburgh": (55.9533, -3.1883),
    "Glasgow": (55.8642, -4.2518), "Bristol": (51.4545, -2.5879),
    "Leeds": (53.8008, -1.5491), "Liverpool": (53.4084, -2.9916),
}
MAPS_NEEDS = {"parking", "toilets", "family_friendly", "pet_friendly", "accessibility"}
ACTIVITY_SYNONYMS = {
    "hiking": ["徒步", "步行", "散步", "远足", "登山", "hiking", "walking", "walk", "trail"],
    "cycling": ["骑行", "骑车", "自行车", "单车", "cycling", "biking", "bike"],
    "camping": ["露营", "帐篷", "camping", "campsite"],
    "birdwatching": ["观鸟", "鸟类", "鸟", "birdwatching", "birding"],
    "beach_coast": ["海滩", "海边", "游泳", "海岸", "beach", "coast", "swimming"],
    "geology": ["地质", "岩石", "地貌", "geology", "geosite"],
    "nature": ["自然", "生态", "野生动物", "nature", "ecology", "wildlife"],
}
MAPS_NEED_SYNONYMS = {
    "parking": ["停车", "停车场", "parking", "car park"],
    "toilets": ["厕所", "洗手间", "toilet", "restroom"],
    "family_friendly": ["儿童", "孩子", "亲子", "家庭", "family", "kid", "child"],
    "pet_friendly": ["宠物", "带狗", "遛狗", "狗", "dog", "pet"],
    "accessibility": ["无障碍", "轮椅", "accessible", "wheelchair"],
}


def save_history(result):
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else []
        history.append(result)
        HISTORY_PATH.write_text(json.dumps(history[-20:], ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError):
        pass


def number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def detect_tags(text, dictionary):
    text = text.lower()
    return [tag for tag, terms in dictionary.items() if any(term.lower() in text for term in terms)]


def point_in_ring(lng, lat, ring):
    inside = False
    for index, point in enumerate(ring):
        other = ring[index - 1]
        if ((point[1] > lat) != (other[1] > lat)) and lng < (other[0] - point[0]) * (lat - point[1]) / (other[1] - point[1] or 1e-12) + point[0]:
            inside = not inside
    return inside


def geometry_polygons(geometry):
    if not geometry:
        return []
    if geometry.get("type") == "Polygon":
        return [geometry.get("coordinates", [])]
    if geometry.get("type") == "MultiPolygon":
        return geometry.get("coordinates", [])
    return []


def point_in_polygon(point, polygon):
    return bool(polygon) and point_in_ring(point[0], point[1], polygon[0]) and not any(point_in_ring(point[0], point[1], hole) for hole in polygon[1:])


def orientation(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(a, b, c, d):
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]) or max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    left, right, top, bottom = orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b)
    return (left == 0 or right == 0 or (left > 0) != (right > 0)) and (top == 0 or bottom == 0 or (top > 0) != (bottom > 0))


def rings_intersect(first, second):
    return any(segments_intersect(a, first[(index + 1) % len(first)], c, second[(other + 1) % len(second)]) for index, a in enumerate(first) for other, c in enumerate(second))


def ring_bounds(ring):
    return (min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring))


def reachability_relation(green_geometry, travel_collection):
    # Reject disjoint polygon pairs before the quadratic vertex/edge comparisons.
    travel_polygons = [(polygon, ring_bounds(polygon[0]))
                       for feature in travel_collection.get('features', [])
                       for polygon in geometry_polygons(feature.get('geometry', feature))
                       if polygon and polygon[0]]
    for green_polygon in geometry_polygons(green_geometry):
        if not green_polygon or not green_polygon[0]:
            continue
        west, south, east, north = ring_bounds(green_polygon[0])
        for travel_polygon, (left, bottom, right, top) in travel_polygons:
            if east < left or right < west or north < bottom or top < south:
                continue
            if any(point_in_polygon(point, travel_polygon) for point in green_polygon[0]) or any(point_in_polygon(point, green_polygon) for point in travel_polygon[0]):
                return 'overlaps_reachable_area'
            if rings_intersect(green_polygon[0], travel_polygon[0]):
                return 'edge_contact'
    return 'outside_reachable_area'


def node_json(script, payload):
    completed = subprocess.run(["node", str(ROOT / script)], input=json.dumps(payload), text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=85, check=False)
    if completed.returncode:
        raise ValueError(f"{script} failed: {completed.stderr.strip() or 'unknown error'}")
    return json.loads(completed.stdout)


def fallback_reason(candidate):
    activity = ", ".join(candidate.get("activity_score_breakdown", {}).keys()) or "活动"
    score = number(candidate.get("activity_score"), 0.0)
    distance = number(candidate.get("distance_km"), 0.0)
    access = candidate.get("access") or "未标注"
    return f"{activity.title()} score {score:.2f}; about {distance:.1f} km away; access: {access}."


def exploration_data():
    display_path = ROOT / "green_spaces_display.geojson"
    if display_path.exists():
        return json.loads(display_path.read_text(encoding="utf-8"))
    dataset = json.loads((ROOT / "natural_assets_2.geojson").read_text(encoding="utf-8"))
    allowed = {"name", "best_overall", "hiking_score", "cycling_score", "camping_score", "birdwatching_score", "coast_score", "geology_score", "scaled_eco_status"}
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": feature.get("geometry"), "properties": {key: feature.get("properties", {}).get(key, 0) for key in allowed}}
        for feature in dataset.get("features", [])
    ]}


def build_request(payload):
    city = payload.get("city", "Glasgow")
    if city not in CITIES:
        city = "Selected map point"
    note = str(payload.get("user_note", "")).strip()
    detected_activities = detect_tags(note, ACTIVITY_SYNONYMS)
    activities = [{"tag": tag, "weight": 1} for tag in detected_activities]
    if not activities:
        raise ValueError("Please describe at least one activity, such as 徒步、骑行、露营、观鸟、海滩或地质探索。")
    needs = detect_tags(note, MAPS_NEED_SYNONYMS)
    maps_needs = [{"tag": tag, "weight": 1 / len(needs)} for tag in needs] if needs else []
    latitude, longitude = number(payload.get("latitude"), None), number(payload.get("longitude"), None)
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        latitude, longitude = CITIES.get(city, CITIES["Glasgow"])
    return {
        "location": {"latitude": latitude, "longitude": longitude, "radius_km": 500},
        "travel_time": {"minutes": max(5, min(180, int(number(payload.get("travel_minutes"), 60)))), "transport": payload.get("transport", "driving+ferry")},
        "activities": activities,
        "hard_constraints": {"access_allowed": bool(payload.get("access_allowed", True))},
        "maps_needs": maps_needs,
        "top_n": 5,
        "weights": {"activity": 0.75, "location": 0.25, "maps": 0.15},
        "user_note": note,
        "parsed_intent": {"activities": detected_activities, "maps_needs": needs, "origin_label": city},
    }


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        compressed = len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", "")
        if compressed:
            body = gzip.compress(body, compresslevel=5)
        self.send_response(status)
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self.send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path.split("?", 1)[0] == "/reports/followup-fixes":
            report = ROOT / "followup_fixes_20261023" / "项目补充设计与修复说明.html"
            if not report.is_file():
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Report not found."})
                return
            body = report.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/stations":
            self.send_json(HTTPStatus.OK, station_filter.station_data())
            return
        if self.path == "/api/green-spaces":
            self.send_json(HTTPStatus.OK, exploration_data())
            return
        if self.path == "/api/config":
            # A Mapbox `pk.` token is intentionally a browser token. Keeping it
            # in .env prevents it being committed with the demo; restrict it to
            # this local URL / the eventual deployed domain in Mapbox settings.
            token = recommend_demo.read_env_value("MAPBOX_PUBLIC_TOKEN")
            self.send_json(HTTPStatus.OK, {
                "mapbox_public_token": token if token and token.startswith("pk.") else None,
            })
            return
        if self.path in {"/", "/index.html"}:
            self.path = "/recommendation_web_demo.html"
        if self.path not in {"/recommendation_web_demo.html", "/dialogue_ui.js", "/map_layout.js", "/map_layout.css"}:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/chat":
            try:
                import dialogue_service
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 20000:
                    raise ValueError("Invalid request size.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object.")
                self.send_json(HTTPStatus.OK, dialogue_service.handle(payload))
            except (ValueError, OSError) as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if self.path != "/api/recommend":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 20_000:
                raise ValueError("Request is too large.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            request = build_request(payload)
            station_filter.station_data()
            request['hard_constraints']['station_boundary_max_km'] = station_filter.LIMIT_KM
            dataset = json.loads((ROOT / "natural_assets_2.geojson").read_text(encoding="utf-8"))
            travel = node_json("traveltime_isochrone.mjs", {"latitude": request["location"]["latitude"], "longitude": request["location"]["longitude"], **request["travel_time"]})
            def reachable_filter(candidate):
                relation = reachability_relation(candidate.get("_geometry"), travel)
                candidate["reachability"] = relation
                if relation == "outside_reachable_area":
                    return False
                candidate['nearest_station'] = station_filter.nearest_station(candidate.get('_geometry'))
                return candidate['nearest_station'] is not None
            result = recommend_demo.run(request, dataset, use_maps=bool(payload.get("use_maps", True)), candidate_filter=reachable_filter)
            try:
                reasons = node_json("groq_reasons.mjs", result["recommendations"])
                by_name = {item.get("name"): item.get("reason") for item in reasons if isinstance(item, dict)}
                for candidate in result["recommendations"]:
                    candidate["llm_recommendation_reason"] = by_name.get(candidate["name"]) or fallback_reason(candidate)
                result["llm_generation"] = {"status": "ok", "provider": "groq", "returned_reason_count": len(by_name)}
            except Exception as exc:
                for candidate in result["recommendations"]:
                    candidate["llm_recommendation_reason"] = fallback_reason(candidate)
                result["llm_generation"] = {"status": "fallback", "provider": "structured_data", "message": str(exc)}
            result["parsed_intent"] = request["parsed_intent"]
            result['method']['station_rule'] = 'After travel-area filtering, require a station within 2 km of the polygon boundary (spherical straight-line distance, not walking distance). Station reachability itself is not verified.'
            result['method']['candidate_rule'] += ' Require station-to-boundary distance <= 2 km before ranking.'
            result["travel_time"] = {"status": "ok", **request["travel_time"], "geojson": travel}
            save_history(result)
            self.send_json(HTTPStatus.OK, result)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Recommendation request failed: {exc}"})


def main():
    parser = argparse.ArgumentParser(description="Serve the local recommendation web demo.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Recommendation demo: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
