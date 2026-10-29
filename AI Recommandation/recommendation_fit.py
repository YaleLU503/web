# -*- coding: utf-8 -*-
"""Match user requirements to explicit dataset, place-summary and review evidence."""
import re
from visitor_reviews import component_scope, INTERESTS

LABELS={'nature':'natural surroundings','hiking':'walking','family_friendly':'taking children','toilets':'toilets','pet_friendly':'bringing a dog','birdwatching':'birdwatching','cycling':'cycling','camping':'camping','beach_coast':'coastal recreation','geology':'geology','parking':'parking','accessibility':'accessibility'}
ACTIVITY_FIT={
 'nature':'The ecological-value signal is relevant to your interest in natural surroundings. It does not establish scenic beauty or wildlife sightings.',
 'hiking':'The mapped long-distance walking-route indicator is relevant to your wish to walk. It does not establish an easy route or suitability for children.',
 'birdwatching':'Recorded bird and reserve indicators are relevant to birdwatching; they do not guarantee a sighting.',
 'cycling':'Mapped cycle-route indicators are relevant to cycling; surface and safety are not established.',
 'camping':'Mapped campsite indicators are relevant to camping; permission and availability are not established.',
 'beach_coast':'Mapped coastal-recreation indicators match your coastal interest; current conditions are not established.',
 'geology':'Mapped geological-diversity indicators match your geology interest; access to each feature is not established.'
}
LABELS['playground']='playground'


def build_requirement_matches(candidate,needs=None):
    matches=[]
    for tag,value in candidate.get('activity_score_breakdown',{}).items():
        matches.append({'requirement':LABELS.get(tag,tag),'status':'dataset_indicator','explanation':f"{float(value['raw_score']):.2f}/1.00. "+ACTIVITY_FIT.get(tag,'This is a dataset indicator, not a visitor rating.')})
    for tag,priority in (needs or {}).items():
        fact=candidate.get('facility_evidence',{}).get(tag,{'status':'unknown'})
        if fact.get('status')=='yes':text='Supported by a matched Google place summary; this is not a real-time guarantee.'
        elif fact.get('status')=='no':text='The checked source reports this is not provided; this requirement is not satisfied.'
        else:text='Not verified by sufficiently matched evidence. This place is not confirmed to satisfy this requirement.'
        matches.append({'requirement':LABELS.get(tag,tag),'priority':priority,'status':fact.get('status','unknown'),'explanation':text})
    candidate['requirement_matches']=matches
    return matches


def google_context(candidate):
    grounding=candidate.get('maps_grounding',{})
    if grounding.get('status')!='ok' or not grounding.get('summary'):return None
    for place in grounding.get('places',[]):
        scope,title=component_scope(candidate,place)
        if not scope:continue
        tags=list(candidate.get('activity_score_breakdown',{}))+list(candidate.get('facility_evidence',{}))
        sentences=re.split(r'(?<=[.!?])\s+',grounding['summary'])
        def relevance(sentence):return sum(bool(re.search(INTERESTS[k],sentence,re.I)) for k in tags if k in INTERESTS)
        sentence=max(sentences,key=relevance)
        words=sentence.split();excerpt=' '.join(words[:18])+(' …' if len(words)>18 else '')
        return {'scope':scope,'place_name':title,'excerpt':excerpt,'summary':grounding['summary'],'source_url':place.get('attribution',{}).get('url'),'reviews_url':place.get('googleMapsLinks',{}).get('reviewsUrl'),'retrieved_at':grounding.get('retrieved_at')}
    return None


def explain_fit(candidate,needs=None):
    matches=build_requirement_matches(candidate,needs)
    lines=[f"Why {candidate['name']} matches your request:"]
    for match in matches:
        lines.append(f"• {match['requirement'].capitalize()}: {match['explanation']}")
    context=google_context(candidate)
    if context:
        if context['scope']=='geographic_alias':
            lines.append(f"Google identifies this location as {context['place_name']}. Its related name and geographic position match the dataset green space, so its information is used as supporting evidence. Conditions can vary across the site.")
        elif context['scope']=='component_only':
            lines.append(f"Google returned {context['place_name']}, only one component of this dataset's combined green space. Its information cannot verify the whole combined area.")
        lines.append('Google place-summary excerpt (not an individual review): “'+context['excerpt']+'”')
        if context.get('source_url'):lines.append('Place source: '+context['source_url'])
    else:lines.append('Google place context: no sufficiently matched place summary was available.')
    reviews=candidate.get('visitor_reviews',{})
    if reviews.get('status')=='ok':
        summary=reviews.get('review_summary',{})
        if summary.get('text',{}).get('text') and summary.get('reviewsUri') and summary.get('disclosureText',{}).get('text'):
            lines.append('Google review summary for '+reviews.get('place_name',candidate['name'])+': '+summary['text']['text'])
            lines.append(summary['disclosureText']['text'])
            lines.append('Read reviews on Google Maps: '+summary['reviewsUri'])
            if summary.get('flagContentUri'):lines.append('Report this summary: '+summary['flagContentUri'])
        else:lines.append('Google did not return a displayable review summary for this place. No review consensus has been inferred.')
        if reviews.get('scope')=='geographic_alias':lines.append('Visitor feedback is from the geographically matched Google place '+reviews['place_name']+'. It supports the recommendation but does not prove identical conditions throughout the green space.')
        elif reviews.get('scope')=='component_only':lines.append('The visitor reviews below concern '+reviews['place_name']+' only, not the entire combined dataset area.')
        for review in reviews.get('excerpts',[]):
            labels=', '.join(LABELS.get(k,k) for k in review['interest_tags'])
            lines.append(f"Visitor excerpt mentioning {labels}: “{review['quote']}” — {review['author']}, {(review.get('published_at') or 'date not returned')[:10]}")
            if review.get('review_url') or review.get('author_url'):lines.append(review.get('review_url') or review['author_url'])
        if not reviews.get('excerpts'):lines.append('Google returned no individual review text for this place in this request.' if not reviews.get('returned_count') else 'The returned individual reviews did not contain relevant excerpts for your selected interests.')
        if reviews.get('reviews_url'):lines.append('Read visitor reviews: '+reviews['reviews_url'])
        if reviews.get('excerpts'):lines.append('Visitor opinions are supporting context, not proof of facilities, wildlife sightings or suitability for every family.')
    elif reviews.get('status')=='api_unavailable':lines.append('Individual visitor reviews could not be retrieved with the current Places API access. The place summary above is not a substitute for review text.')
    else:lines.append('Individual visitor reviews have not been verified for this candidate.')
    station=candidate.get('nearest_station')
    if station:lines.append(f"Rail access: {station['name']} is {station['boundary_distance_km']:.2f} km from the boundary in a straight line; the entrance and walking route are not verified.")
    if any(match['status']=='unknown' for match in matches):lines.append('This is a candidate matching the scored interests, not a claim that every preference is confirmed.')
    return '\n'.join(lines)
