"""Grounded score explanations from the project's RAG scoring documentation.
No model-generated claims, invented thresholds, or inferred facility availability.
"""
from recommendation_fit import build_requirement_matches, google_context

RULES = {
 'hiking': ('Walking / hiking','Uses mapped long-distance walking-route length, combined with ecological value.','It does not measure slope, route difficulty, pushchair access or every local footpath.'),
 'nature': ('Nature','Uses the dataset\'s normalized ecological-value indicator. Higher values indicate a stronger ecological-value signal within this scoring system.','It does not guarantee scenic views, wildlife sightings or quiet conditions.'),
 'cycling': ('Cycling','Combines mapped dedicated cycle paths and National Cycle Network routes with ecological value.','It does not establish surface quality, traffic safety or suitability for a particular bicycle.'),
 'camping': ('Camping','Uses mapped campsite points inside or up to 2 km from the asset, combined with ecological value.','It does not establish permission to camp, opening dates or booking availability.'),
 'birdwatching': ('Birdwatching','Combines recorded bird sightings, Important Bird and Biodiversity Areas, and RSPB reserves with ecological value.','It does not guarantee a sighting or identify current species at the site.'),
 'beach_coast': ('Coast','Uses official bathing-water sites and coastal award counts, combined with ecological value.','It does not confirm current bathing-water quality, weather or swimming safety.'),
 'geology': ('Geology','Uses geological and geomorphological diversity, including Great Geosites. The project documentation excludes the ecological-value component from this category.','It does not establish access to an individual geological feature.')
}


def enrich_candidate(candidate, needs=None):
    items=[]
    breakdown=candidate.get('activity_score_breakdown',{})
    evidence=candidate.get('dataset_evidence',{})
    for tag,value in breakdown.items():
        if tag not in RULES: continue
        label,rule,limit=RULES[tag]
        items.append({'label':label,'score':value.get('raw_score',0),'weight':value.get('weight',0),'explanation':rule,'limitation':limit})
    candidate['score_explanations']=items
    candidate['scoring_note']='Category indicators are normalized to 0–1. The project scoring guide describes arithmetic means of normalized indicators, with an ecological-value component except for geology. Your activity component is the weighted mean of the selected category scores. These are model scores, not percentages or visitor ratings.'
    candidate['scoring_source']='Project scoring guide: RAG/评分标准.docx; Nature uses scaled_eco_status in the dataset.'
    if items:
        labels=', '.join(f"{item['label']} ({float(item['score']):.2f})" for item in items)
        candidate['llm_recommendation_reason']='Recommended for your selected activity mix: '+labels+'. The explanations below describe what each score actually measures.'
    candidate['maps_support']=None
    maps=candidate.get('maps_grounding',{})
    if maps.get('status')=='ok' and candidate.get('maps_entity_match',{}).get('status') in {'exact_or_subtype_name_match','related_named_place','spatial_alias_match'} and maps.get('summary'):
        candidate['maps_support']={'summary':maps['summary'],'retrieved_at':maps.get('retrieved_at'),'source':'Google Maps returned summary'}
    build_requirement_matches(candidate,needs)
    candidate['google_context']=google_context(candidate)
    if items:
        candidate['llm_recommendation_reason']=' '.join(item['explanation'] for item in candidate['requirement_matches'] if item['status']=='dataset_indicator')
    return candidate


def enrich_result(result):
    if result:
        for candidate in result.get('recommendations',[]):enrich_candidate(candidate,result.get('request',{}).get('dialogue_needs',{}))
    return result
