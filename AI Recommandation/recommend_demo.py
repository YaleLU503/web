"""Local green-space recommendation demo with optional Maps Grounding Lite enrichment.

No third-party Python packages are required. The optional Maps request reads
GOOGLE_MAPS_API_KEY from .env and never writes the key to an output file.
"""

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / "natural_assets_2.geojson"
DEFAULT_REQUEST = ROOT / "recommendation_request.json"
DEFAULT_OUTPUT = ROOT / "recommendation_demo_output.json"
MAPS_ENDPOINT = "https://mapstools.googleapis.com/mcp"

ACTIVITY_FIELDS = {
    "hiking": {"score": "hiking_score", "evidence": ["len_trails", "access"]},
    "cycling": {"score": "cycling_score", "evidence": ["cyclepath", "natcyclenetwork", "access"]},
    "camping": {"score": "camping_score", "evidence": ["campsites", "access"]},
    "birdwatching": {"score": "birdwatching_score", "evidence": ["bird_sightings_number", "important_bird_area", "rspb_sites"]},
    "beach_coast": {"score": "coast_score", "evidence": ["beach_presence", "bathing_waters", "coast_award_sum"]},
    "geology": {"score": "geology_score", "evidence": ["great_geosite", "georichness"]},
    "nature": {"score": "scaled_eco_status", "evidence": ["eco_status"]},
}

MAPS_NEED_TERMS = {
    "playground": ["playground", "play area", "slides", "swings"],
    "parking": ["parking", "car park"],
    "toilets": ["toilet", "restroom", "washroom"],
    "family_friendly": ["family", "kid", "child", "children"],
    "pet_friendly": ["dog", "pet-friendly", "pet friendly"],
    "accessibility": ["wheelchair", "accessible", "accessibility"],
}

GENERIC_PLACE_WORDS = {"forest", "park", "country", "national", "landscape", "common", "green", "space"}


def read_env_value(name: str) -> Optional[str]:
    """Read one .env value without exporting or printing it."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return os.environ.get(name)
    found = None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            # Later entries override earlier ones, matching normal .env use.
            found = value.strip().strip('"').strip("'")
    return found or os.environ.get(name)


def numeric(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def all_points(value):
    """Yield coordinate pairs from arbitrary GeoJSON coordinate nesting."""
    if isinstance(value, list) and len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
        yield value[0], value[1]
    elif isinstance(value, list):
        for item in value:
            yield from all_points(item)


def geometry_center(geometry: dict) -> Optional[Tuple[float, float]]:
    points = list(all_points(geometry.get("coordinates", [])))
    if not points:
        return None
    longitudes, latitudes = zip(*points)
    return (min(latitudes) + max(latitudes)) / 2, (min(longitudes) + max(longitudes)) / 2


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.asin(math.sqrt(a))


def access_allowed(value) -> bool:
    return str(value or "").strip().lower() not in {"no", "private", "closed", "prohibited"}


def normalised_activity_weights(activities: list[dict]) -> list[dict]:
    valid = [item for item in activities if item.get("tag") in ACTIVITY_FIELDS and numeric(item.get("weight")) > 0]
    total = sum(numeric(item["weight"]) for item in valid)
    if not total:
        raise ValueError("At least one supported activity with a positive weight is required.")
    return [{**item, "weight": numeric(item["weight"]) / total} for item in valid]


def maps_query(name: str, needs: list[str], activities=None) -> str:
    requested = ", ".join(list(activities or []) + list(needs)) or "visitor activities and facilities"
    return (
        f"{name}, United Kingdom: provide factual visitor information about {requested}. "
        "Describe how the place relates to the requested activities and facilities. Distinguish place facts from any visitor-feedback themes actually returned. Do not invent reviews, quotes, wildlife sightings, route ease or facility availability. Clearly identify partial place matches. Only include details supported by Google Maps data."
    )


def call_maps_grounding(query: str, api_key: str) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_places",
            "arguments": {"textQuery": query, "languageCode": "en", "regionCode": "GB"},
        },
    }
    request = urllib.request.Request(
        MAPS_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"status": "error", "message": f"Maps request failed with HTTP {exc.code}."}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"status": "error", "message": f"Maps request failed: {exc.reason if hasattr(exc, 'reason') else exc}."}

    result = body.get("result", {})
    structured = result.get("structuredContent", {})
    if not structured:
        return {"status": "error", "message": body.get("error", {}).get("message", "Maps returned no structured content.")}
    return {
        "status": "ok",
        "summary": structured.get("summary", ""),
        "places": structured.get("places", []),
    }


def evaluate_maps_needs(summary: str, needs: list[dict]) -> tuple[dict, float]:
    text = summary.lower()
    results, total_weight, confirmed_weight = {}, 0.0, 0.0
    for item in needs:
        tag, weight = item.get("tag"), numeric(item.get("weight"))
        if tag not in MAPS_NEED_TERMS or weight <= 0:
            continue
        total_weight += weight
        confirmed = any(term in text for term in MAPS_NEED_TERMS[tag])
        results[tag] = "confirmed_in_summary" if confirmed else "unknown"
        if confirmed:
            confirmed_weight += weight
    return results, confirmed_weight / total_weight if total_weight else 0.0


def maps_entity_match(place_name: str, places: list[dict], geometry=None) -> dict:
    """Check whether Maps appears to describe the requested green space, not a nearby POI."""
    if geometry:
        from geospatial_match import spatial_alias
        for place in places:
            match=spatial_alias({'name':place_name,'_geometry':geometry},place,geometry)
            if match:
                return {**match,'source_titles':[p.get('attribution',{}).get('title','') for p in places]}
        if places and all(all(isinstance(p.get('location',{}).get(k),(int,float)) for k in ('latitude','longitude')) for p in places):
            return {'status':'spatial_mismatch','source_titles':[p.get('attribution',{}).get('title','') for p in places]}
    query_tokens = set(re.findall(r"[a-z]+", (place_name or "").lower())) - GENERIC_PLACE_WORDS
    titles = [item.get("attribution", {}).get("title", "") for item in places]
    best_overlap = 0
    for title in titles:
        title_tokens = set(re.findall(r"[a-z]+", title.lower()))
        best_overlap = max(best_overlap, len(query_tokens & title_tokens))
        if place_name and place_name.lower() in title.lower():
            return {"status": "exact_or_subtype_name_match", "source_titles": titles}
    if query_tokens and best_overlap == len(query_tokens):
        return {"status": "related_named_place", "source_titles": titles}
    if best_overlap:
        return {"status": "weak_name_match", "source_titles": titles}
    return {"status": "no_name_match", "source_titles": titles}


def make_candidate(feature: dict, request: dict, activity_weights: list[dict]) -> Optional[dict]:
    properties = feature.get("properties", {})
    location = request["location"]
    center = geometry_center(feature.get("geometry", {}))
    if center is None:
        return None
    distance_km = haversine_km(location["latitude"], location["longitude"], center[0], center[1])
    if distance_km > location["radius_km"]:
        return None
    if request.get("hard_constraints", {}).get("access_allowed") and not access_allowed(properties.get("access")):
        return None

    score_breakdown, activity_score = {}, 0.0
    for activity in activity_weights:
        tag, weight = activity["tag"], activity["weight"]
        field = ACTIVITY_FIELDS[tag]["score"]
        raw_score = numeric(properties.get(field))
        weighted_score = raw_score * weight
        activity_score += weighted_score
        score_breakdown[tag] = {"score_field": field, "raw_score": raw_score, "weight": weight, "weighted_score": weighted_score}

    location_score = max(0.0, 1 - distance_km / location["radius_km"])
    weights = request.get("weights", {})
    activity_weight = numeric(weights.get("activity"), 0.75)
    location_weight = numeric(weights.get("location"), 0.25)
    base_weight_total = activity_weight + location_weight
    if base_weight_total <= 0:
        raise ValueError("The activity and location weights must have a positive total.")
    activity_weight, location_weight = activity_weight / base_weight_total, location_weight / base_weight_total
    base_score = activity_weight * activity_score + location_weight * location_score

    evidence = {field: properties.get(field) for activity in activity_weights for field in ACTIVITY_FIELDS[activity["tag"]]["evidence"]}
    return {
        "place_id": properties.get("fid"),
        "name": properties.get("name"),
        "geometry_center": {"latitude": center[0], "longitude": center[1]},
        "distance_km": round(distance_km, 3),
        "access": properties.get("access"),
        "activity_score": activity_score,
        "location_score": location_score,
        "base_score": base_score,
        "activity_score_breakdown": score_breakdown,
        "dataset_evidence": evidence,
        "_geometry": feature.get("geometry"),
    }


def enrich_maps_candidates(selected, request, use_maps=True):
    activity_weights = normalised_activity_weights(request.get('activities', []))
    maps_needs = request.get("maps_needs", [])
    api_key = read_env_value("GOOGLE_MAPS_API_KEY") if use_maps else None

    for candidate in selected:
        candidate["maps_grounding"] = {"status": "not_requested"}
        candidate["maps_entity_match"] = {"status": "not_requested"}
        candidate["maps_need_status"] = {item.get("tag"): "not_requested" for item in maps_needs}
        candidate["maps_score"] = 0.0
        if not use_maps:
            candidate["final_score"] = candidate["base_score"]
            continue
        if not api_key:
            candidate["maps_grounding"] = {"status": "skipped", "message": "GOOGLE_MAPS_API_KEY was not found in .env."}
            candidate["final_score"] = candidate["base_score"]
            continue
        query = maps_query(candidate["name"], [item.get("tag", "") for item in maps_needs], [item["tag"] for item in activity_weights])
        response = call_maps_grounding(query, api_key)
        candidate["maps_grounding"] = {"query": query, **response, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        if response.get("status") == "ok":
            entity_match = maps_entity_match(candidate["name"], response.get("places", []),candidate.get("_geometry"))
            candidate["maps_entity_match"] = entity_match
            if entity_match["status"] in {"exact_or_subtype_name_match", "related_named_place", "spatial_alias_match"}:
                status, maps_score = evaluate_maps_needs(response.get("summary", ""), maps_needs)
            else:
                status, maps_score = ({item.get("tag"): "unknown" for item in maps_needs}, 0.0)
            candidate["maps_need_status"] = status
            candidate["maps_score"] = maps_score
        maps_weight = min(max(numeric(request.get("weights", {}).get("maps"), 0.15), 0.0), 1.0)
        candidate["final_score"] = candidate["base_score"] + maps_weight * candidate["maps_score"]

    return selected


def run(request: dict, dataset: dict, use_maps: bool, candidate_filter=None, keep_geometry=False) -> dict:
    activity_weights = normalised_activity_weights(request.get("activities", []))
    candidates = [make_candidate(feature, request, activity_weights) for feature in dataset.get("features", [])]
    candidates = [candidate for candidate in candidates if candidate]
    if candidate_filter:
        candidates = [candidate for candidate in candidates if candidate_filter(candidate)]
    candidates.sort(key=lambda item: (-item["base_score"], item["distance_km"], item["name"] or ""))
    top_n = int(request.get("top_n", 5))
    selected = candidates[:top_n]
    enrich_maps_candidates(selected, request, use_maps)

    selected.sort(key=lambda item: (-item["final_score"], item["distance_km"], item["name"] or ""))
    for candidate in selected:
        if not keep_geometry:
            candidate.pop("_geometry", None)
    return {
        "schema_version": "0.1-demo",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "request": request,
        "method": {
            "candidate_rule": "Within radius, travel-time area when supplied, then access hard constraint, then base score ranking.",
            "base_score_formula": "normalised(activity_weight) × activity_score + normalised(location_weight) × location_score",
            "final_score_formula": "base_score + maps_weight × maps_score; Maps only enriches the initial Top N and unknown findings do not lower the base score.",
            "maps_status_note": "confirmed_in_summary is a keyword match in a Maps summary only after a named-place match. Unknown is not a negative finding."
        },
        "candidate_count_after_filters": len(candidates),
        "recommendations": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the green-space recommendation demo.")
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-maps", action="store_true", help="Do not call Maps Grounding Lite.")
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        dataset = json.loads(args.data.read_text(encoding="utf-8"))
        result = run(request, dataset, use_maps=not args.skip_maps)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Demo failed: {exc}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(result['recommendations'])} recommendations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
