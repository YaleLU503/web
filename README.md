# Green-space recommendation demo

## Background and purpose

Finding a suitable green space involves balancing interests, travel time, rail access and practical needs such as toilets or family-friendly facilities. This project brings these considerations into one interactive UK map and conversational recommendation service.

The aim is to help people discover green spaces reachable by train, compare activity-specific indicators, refine their preferences through follow-up conversation, and understand the evidence behind each recommendation.

## [🌿 Open the live website](https://green-space-ai.onrender.com/)

![Green-space recommendation website](AI%20Recommandation/design_preview.png)

## Interaction workflow

1. Choose a city or drag the map marker, set a travel limit, and describe activities.
2. Extract structured intent, validate changes, and retain existing preferences.
3. Calculate reachability and filter green spaces using spatial and station-access constraints.
4. Check facility evidence for ranked candidates, reusing eligible recent evidence.
5. Display recommendations, activity scores and map locations.
6. Accept follow-up changes and explain recommendations using attributable evidence.

## Data sources

- **Green-space geometry and activity indicators** come from the bundled project dataset, natural_assets_2.geojson. The project inherits its provenance and redistribution conditions.
- **Transport POIs and rail connections** are sourced from OpenStreetMap (OSM), retaining stations and railway links classified as operational in the prepared dataset.
- **Reachability** is supplied by TravelTime using the configured travel assumptions.
- **Place and visitor evidence** comes from matched Google Maps / Places responses, with source attribution.
- **Basemap rendering** uses Mapbox and the configured public browser token.

Local UK green-space explorer with a map and persistent multi-turn conversation.
Core dialogue fixes: 2026-10-23; targeted live-model verification: 2026-10-24.

## Run

Requires Python 3.9+ and Node.js 18+ (built-in modules only). The browser loads Mapbox GL from its CDN.

1. Copy `.env.example` to `.env` in this folder and supply your own provider credentials.
2. Run `python recommendation_web_demo.py --port 8766` from this folder.
3. Open http://127.0.0.1:8766/.

Configure Google Maps/Places, Groq, TravelTime and a Mapbox public browser token. API requests may incur charges. Never commit `.env`. Restrict the public Mapbox token to the intended app URLs.

## Current behavior

- Choose an origin city, drag a map point, or describe a supported city in chat. Set a travel limit and activities. There is no departure-date or transport selector.
- Access to an origin station uses public transport or a taxi proxy, followed by train and walking. The three nearest dataset stations are considered without a 2 km origin cutoff. Taxi waiting is not modelled.
- Destination candidates need a station within 2 km of the green-space boundary, measured straight-line, not along a walking route. Only explicitly disallowed access is excluded.
- Preserve eligible, recently verified previous recommendations, then check more ranked candidates until five matches, candidate exhaustion, or 20 new facility checks. Facility cache reuse is limited to six hours and must cover the current needs.
- Required facilities need affirmative evidence; unknown does not mean absent and does not satisfy a requirement.
- Follow-up questions reuse the last explained place and available Google review summaries. Quiet atmosphere and fewer crowds are evaluated separately. Subjective evidence explanations do not rerank recommendations.
- Cancelling a playground requirement cannot implicitly remove family-friendly preferences or accompanying children. Explicit cancellations affect their own fields.
- The map, scores and expandable recommendations are displayed alongside the conversation.

## Implementation

`dialogue_llm.mjs` extracts structured intent through Groq; `dialogue_service.py` validates and merges state and stores sessions locally. `dialogue_policies.py` protects follow-up updates and resolves places. `review_followup.py` validates source quotations. `facility_search.py` manages bounded facility checks and reuse. `station_filter.py`, `train_access.mjs` and `traveltime_train.mjs` handle spatial and travel constraints. `recommendation_fit.py` and `recommendation_explanations.py` explain indicator and facility evidence.

The bundled `natural_assets_2.geojson` supplies project green-space geometry and scores. Transport POIs and rail connections come from OpenStreetMap (OSM), with operational stations and railway links retained during data preparation.

## Local tests

```powershell
python -m unittest test_followup_fixes test_facility_search test_reachability_prefilter test_geospatial_match test_recommendation_evidence test_dialogue_service test_station_filter -q
node --test test_train_access.mjs
```

The Python suite covers 68 checks without live provider calls. Historical transcripts, screenshots, reports, generated outputs, local sessions and credentials are not part of this code submission.

## Limits

This is a local demo, not a production service. Chat processing is serialized. Reference departure time is generated by the backend; estimates do not represent a booked itinerary. Train-mode isochrones can include walking-only journeys; actual boarding and usable park entrances are not individually verified. Reviews are historical opinions, not real-time crowd measurements or guarantees. Unchecked candidates may still qualify. A dedicated next-page / different-candidates workflow is not implemented.

The optional local report URL returns 404 when report artifacts are absent; reports are intentionally excluded from the project-only submission. Local conversations are saved to `dialogue_sessions.sqlite3`; do not publish them.

## Render deployment

Use New > Blueprint and connect this repository on main. The root render.yaml configures a Free Docker web service with Python and Node.js. Enter the six provider configuration values in Render; never commit credentials. The service reads PORT and binds to HOST=0.0.0.0. /healthz is a lightweight health check without external API calls. Add the final site URL to any Mapbox token URL restrictions.

Free instances sleep when idle and local SQLite conversations are ephemeral across restarts/redeployments. Start a new conversation if an old browser session no longer exists. This deployment remains a demonstration with serialized chat processing, not a production multi-user service.

## Tools and services

| Component | Role |
| --- | --- |
| Python | Recommendation service, spatial filtering, state validation and evidence checks |
| Node.js | Model, map-enrichment and travel-service integrations |
| Mapbox GL JS | Interactive map, green-space scores, railways and stations |
| Groq | Structured intent and evidence extraction |
| TravelTime | Travel-time reachability estimates |
| Google Maps / Places | Matched place information and attributable visitor evidence |
| SQLite | Local multi-turn conversation storage |
| Docker and Render | Application packaging and web deployment |
