# -*- coding: utf-8 -*-
"""On-demand Google Places review evidence, preserving attribution and scope."""
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import recommend_demo as rec
from geospatial_match import spatial_alias

INTERESTS={
 'nature':r'\bnature|\bwood|\bforest|\bgrassland|\bdeer|\bwildlife|\banimal|\bscenery|\bgreen',
 'hiking':r'\bwalk|\bhik|\btrail|\bpath',
 'family_friendly':r'\bchild|\bkid|\bfamily|\bfamilies|\bplayground|\bpushchair',
 'toilets':r'\btoilet|\brestroom|\bwashroom|\bwc\b',
 'pet_friendly':r'\bdog|\bpet',
 'birdwatching':r'\bbird', 'cycling':r'\bcycl|\bbike',
 'camping':r'\bcamp', 'beach_coast':r'\bbeach|\bcoast',
 'accessibility':r'\bwheelchair|\baccessible', 'parking':r'\bpark(?:ing)?\b',
 'geology':r'\brock|\bgeolog'
}


def component_scope(candidate,place):
    title=place.get('attribution',{}).get('title','').split(' - Google Maps')[0].strip()
    full=candidate.get('name','')
    match=spatial_alias(candidate,place)
    if match:
        candidate['maps_entity_match']={**candidate.get('maps_entity_match',{}),**match}
        return 'geographic_alias',title
    if candidate.get('maps_entity_match',{}).get('status') in {'exact_or_subtype_name_match','related_named_place'}:
        return 'matched_place',title
    def tokens(s):return set(re.findall(r'[a-z]+',s.lower()))
    for part in re.split(r'\s+and\s+|\s*&\s*',full,flags=re.I):
        if tokens(part)==tokens(title) and tokens(part)-rec.GENERIC_PLACE_WORDS:
            return 'component_only',title
    return None,title


def extract_excerpts(reviews,tags):
    excerpts=[]
    for review in reviews:
        text=review.get('originalText',review.get('text',{})).get('text','')
        if not text:continue
        sentences=re.split(r'(?<=[.!?])\s+|\n+',text)
        ranked=[]
        for sentence in sentences:
            matches=[tag for tag in tags if tag in INTERESTS and re.search(INTERESTS[tag],sentence,re.I)]
            if matches:ranked.append((len(matches),sentence,matches))
        if not ranked:continue
        _,sentence,matches=max(ranked,key=lambda item:item[0])
        words=sentence.split();quote=' '.join(words[:12])+(' …' if len(words)>12 else '')
        author=review.get('authorAttribution',{})
        excerpts.append({'quote':quote,'interest_tags':matches,'author':author.get('displayName','Google Maps reviewer'),'author_url':author.get('uri'),'review_url':review.get('googleMapsUri'),'published_at':review.get('publishTime'),'rating':review.get('rating')})
    excerpts.sort(key=lambda item:-len(item['interest_tags']))
    return excerpts[:2]


def fetch_reviews(candidate,tags):
    result = _fetch_reviews(candidate,tags)
    result['review_summary_requested'] = True
    return result


def _fetch_reviews(candidate,tags):
    places=candidate.get('maps_grounding',{}).get('places',[])
    eligible=[]
    for place in places:
        scope,title=component_scope(candidate,place)
        if scope and place.get('id'):eligible.append((place,scope,title))
    if not eligible:return {'status':'unverified_place','message':'No sufficiently identified Google place was available for review lookup.','excerpts':[]}
    place,scope,title=eligible[0]
    api_key=rec.read_env_value('GOOGLE_MAPS_API_KEY')
    if not api_key:return {'status':'unavailable','message':'Google Places reviews are not configured.','excerpts':[]}
    place_id=str(place['id'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+',place_id):return {'status':'unverified_place','excerpts':[]}
    request=urllib.request.Request('https://places.googleapis.com/v1/places/'+urllib.parse.quote(place_id)+'?languageCode=en',headers={'X-Goog-Api-Key':api_key,'X-Goog-FieldMask':'id,displayName,reviews,reviewSummary,googleMapsUri'})
    try:
        with urllib.request.urlopen(request,timeout=18) as response:data=json.load(response)
    except urllib.error.HTTPError as exc:
        return {'status':'api_unavailable','http_status':exc.code,'message':'Individual reviews could not be retrieved from Places API (New).','excerpts':[]}
    except (urllib.error.URLError,TimeoutError,ValueError):
        return {'status':'unavailable','message':'The review request could not be completed.','excerpts':[]}
    if data.get('id')!=place_id:return {'status':'unverified_place','message':'Google place ID did not match.','excerpts':[]}
    return {'status':'ok','scope':scope,'place_name':data.get('displayName',{}).get('text') or title,'place_id':place_id,'place_url':data.get('googleMapsUri') or place.get('attribution',{}).get('url'),'reviews_url':data.get('reviewSummary',{}).get('reviewsUri') or place.get('googleMapsLinks',{}).get('reviewsUrl'),'review_summary':data.get('reviewSummary') or {},'returned_count':len(data.get('reviews',[])),'excerpts':extract_excerpts(data.get('reviews',[]),tags),'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(),'message':'Visitor opinions; not a guarantee or a representative survey.'}
