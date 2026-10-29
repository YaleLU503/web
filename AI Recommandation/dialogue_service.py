"""Persistent multi-turn state, validated intent updates, skill routing and evidence.
LLM extracts intent; Python owns state, constraints, queries and recorded facts.
"""
import copy
import datetime as dt
import json
import math
import logging
import re
import sqlite3
import threading
import uuid
from functools import lru_cache
from pathlib import Path

import recommend_demo as rec
import station_filter
from recommendation_explanations import enrich_result
from recommendation_fit import explain_fit
from facility_search import select_candidates, coverage_message
from visitor_reviews import fetch_reviews
from dialogue_policies import normalize_followup, review_target
from review_followup import answer_review_followup
from facility_search import candidate_key

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'dialogue_sessions.sqlite3'
LOCK = threading.RLock()
NEEDS = {'toilets','parking','playground','family_friendly','pet_friendly','accessibility'}
LABELS = {'hiking':'Walking / hiking','birdwatching':'Birdwatching','nature':'Nature','cycling':'Cycling','camping':'Camping','beach_coast':'Coast','geology':'Geology','toilets':'Toilets','parking':'Parking','family_friendly':'Family-friendly','pet_friendly':'Pet-friendly','accessibility':'Accessibility'}
LABELS['playground']='Playground'


def database():
    con = sqlite3.connect(DB_PATH)
    con.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
    return con


def read_session(sid):
    try: sid = str(uuid.UUID(sid))
    except (ValueError, TypeError, AttributeError): raise ValueError('Invalid conversation ID. Please start a new conversation.')
    with database() as con:
        row = con.execute('SELECT body FROM sessions WHERE id=?',(sid,)).fetchone()
    if not row: raise ValueError('Conversation not found. Please start a new conversation.')
    return json.loads(row[0])


def save_session(session):
    with database() as con:
        con.execute('INSERT OR REPLACE INTO sessions VALUES (?,?)',(session['id'],json.dumps(session,ensure_ascii=False)))


def new_session():
    return {'id':str(uuid.uuid4()),'state':{'city':None,'minutes':None,'latitude':None,'longitude':None,'activities':{},'needs':{},'travel_party':{},'departure_time':None},'pending':None,'turns':[],'last_result':None,'last_result_state':None}


def normalize_activity_intent(message, intent, state):
    """Protect compound intents and preserve prior activities unless cancelled."""
    intent=copy.deepcopy(intent)
    if intent.get('action') not in {'recommend','clarify'}:
        return intent
    patch=intent.get('patch',{})
    if not isinstance(patch,dict):return intent
    removed=intent.get('removed_activities',[])
    if not isinstance(removed,list) or any(tag not in rec.ACTIVITY_FIELDS for tag in removed):
        raise ValueError('Invalid activity cancellation. Please rephrase.')
    proposed=patch.get('activities')
    if proposed is not None and not isinstance(proposed,dict):return intent
    activities={**state.get('activities',{}),**(proposed or {})}
    for tag in removed:activities.pop(tag,None)
    compound=re.search(r'\bnature[ -]+(?:walk(?:s|ing)?|hik(?:e|es|ing))\b|自然(?:中|里)?(?:散步|徒步)',message,re.I)
    if compound:
        # Leave negated, rejected or replaced compounds to semantic extraction.
        before=message[:compound.start()]
        after=message[compound.end():]
        negative=re.search(r"\b(?:no|not|never|avoid|stop|cancel|without|instead of|rather than|don.t|don’t)\b|不|取消|不要",before,re.I) or re.match(r"\s*(?:isn.t|is not|isn’t|not|is no longer|不要)",after,re.I)
        if not negative:
            activities.setdefault('nature',3)
            activities.setdefault('hiking',3)
    if proposed is not None or removed or (compound and not negative):
        patch['activities']=activities
        intent['patch']=patch
    return intent


def validate_patch(state, patch, cities):
    if not isinstance(patch,dict): raise ValueError('Unable to parse your request. Please rephrase.')
    out=copy.deepcopy(state)
    if 'city' in patch:
        city = patch['city']
        # Models may echo the current origin label. A map label is not a city
        # lookup: preserve its already validated coordinates without geocoding.
        if city == state.get('city') and state.get('latitude') is not None and state.get('longitude') is not None:
            pass
        elif city in cities:
            out['city']=city; out['latitude'],out['longitude']=cities[city]
        else:
            raise ValueError('That city is not in the list. Please drag the map marker to your origin.')
    if 'minutes' in patch:
        n=patch['minutes']
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 5<=n<=180: raise ValueError('Please use a travel limit between 5 and 180 minutes.')
        out['minutes']=int(n)
    if 'activities' in patch:
        values=patch['activities']
        if not isinstance(values,dict) or any(k not in rec.ACTIVITY_FIELDS or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<=5 for k,v in values.items()): raise ValueError('Unable to interpret activity preferences. Please rephrase.')
        out['activities']=values
    if 'needs' in patch:
        if not isinstance(patch['needs'],dict): raise ValueError('Invalid facility preferences.')
        for key,value in patch['needs'].items():
            if key not in NEEDS or value not in {'preferred','required','remove'}: raise ValueError('Unable to interpret facility preferences.')
            if value=='remove': out['needs'].pop(key,None)
            else: out['needs'][key]=value
    if 'travel_party' in patch:
        party=patch['travel_party']
        if not isinstance(party,dict) or any(k!='children' or not isinstance(v,bool) for k,v in party.items()):
            raise ValueError('Invalid travel-party information.')
        out.setdefault('travel_party',{}).update(party)
    return out


def apply_ui(state, ui, cities):
    if not isinstance(ui,dict): raise ValueError('Invalid page settings.')
    patch={k:ui[k] for k in ('city','minutes') if k in ui and ui[k] is not None}
    out=validate_patch(state,patch,cities)
    if 'city' in ui and ui['city'] is None:
        out.update(city=None,latitude=None,longitude=None)
    if 'latitude' in ui or 'longitude' in ui:
        lat,lon=ui.get('latitude'),ui.get('longitude')
        if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (lat,lon)) or not -90<=lat<=90 or not -180<=lon<=180: raise ValueError('Invalid map coordinates.')
        out.update(latitude=lat,longitude=lon)
        if out['city'] not in cities or (abs(lat-cities[out['city']][0])>.001 or abs(lon-cities[out['city']][1])>.001): out['city']='Selected map point'
    if 'departure_time' in ui:
        try:
            date=dt.datetime.fromisoformat(ui['departure_time'].replace('Z','+00:00'))
            if date.tzinfo is None: raise ValueError()
        except (ValueError,TypeError,AttributeError): raise ValueError('Invalid reference departure time.')
        out['departure_time']=date.isoformat()
    return out


def state_summary(state):
    activity=', '.join(LABELS.get(k,k) for k in sorted(state['activities'],key=state['activities'].get,reverse=True)) or 'Activities not set'
    needs='; '.join(f"{LABELS[k]}: {'required' if v=='required' else 'preferred'}" for k,v in state['needs'].items())
    return f"{state['city'] or 'Origin not set'} · {state['minutes'] or 'not set'} min · Transit / taxi + train + walking · {activity}" + ('; '+needs if needs else '') + ('; Travelling with children' if state.get('travel_party',{}).get('children') else '')


@lru_cache(maxsize=1)
def dataset():
    return json.loads((ROOT/'natural_assets_2.geojson').read_text(encoding='utf-8'))


def box(geometry):
    points=list(rec.all_points((geometry or {}).get('coordinates',[])))
    return (min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)) if points else None


def overlap(a,b):
    return a and b and a[0]<=b[2] and b[0]<=a[2] and a[1]<=b[3] and b[1]<=a[3]


@lru_cache(maxsize=4096)
def cached_box(geometry_json): return box(json.loads(geometry_json))


@lru_cache(maxsize=32)
def travel_area(lat,lon,minutes,departure):
    from recommendation_web_demo import node_json
    return node_json('traveltime_train.mjs',{'latitude':lat,'longitude':lon,'minutes':minutes,'departure_time':departure})


def verify_facilities(result, needs, invoke):
    """Require exact-source affirmative evidence; old keyword scores are not proof."""
    places=result['recommendations']
    for p in places: p['facility_evidence']={k:{'status':'unknown','quote':''} for k in needs}
    eligible=[p for p in places if p.get('maps_entity_match',{}).get('status') in {'exact_or_subtype_name_match','related_named_place','spatial_alias_match'} and p.get('maps_grounding',{}).get('status')=='ok']
    if needs and eligible:
        data=invoke('dialogue_llm.mjs',{'mode':'facilities','needs':list(needs),'places':[{'name':p['name'],'summary':p['maps_grounding']['summary']} for p in eligible]})
        entries={p.get('name'):p for p in data.get('places',[]) if isinstance(p,dict)}
        for p in eligible:
            source=p['maps_grounding']['summary']
            for need in needs:
                evidence=entries.get(p['name'],{}).get('needs',{}).get(need,{})
                status,quote=evidence.get('status'),evidence.get('quote','')
                if status in {'yes','no'} and isinstance(quote,str) and len(quote.strip())>=8 and quote in source:
                    p['facility_evidence'][need]={'status':status,'quote':quote}
    for p in places:
        p['final_score']=p['base_score']+.15*(sum(v['status']=='yes' for v in p['facility_evidence'].values())/len(needs) if needs else 0)
    required=[k for k,v in needs.items() if v=='required']
    result['checked_candidate_count']=len(places)
    result['recommendations']=[p for p in places if all(p['facility_evidence'][k]['status']=='yes' for k in required)]
    result['recommendations'].sort(key=lambda p:-p['final_score'])
    result['matching_checked_count']=len(result['recommendations'])
    result['recommendations']=result['recommendations'][:5]


def recommend(state, use_maps=True, previous_result=None):
    from recommendation_web_demo import node_json, reachability_relation
    area=travel_area(state['latitude'],state['longitude'],state['minutes'],state['departure_time'])
    boxes=[box(f['geometry']) for f in area['features']]
    request={'location':{'latitude':state['latitude'],'longitude':state['longitude'],'radius_km':500},'activities':[{'tag':k,'weight':v} for k,v in state['activities'].items()],'hard_constraints':{'access_allowed':True,'station_boundary_max_km':2},'maps_needs':[{'tag':k,'weight':1} for k in state['needs']],'top_n':5,'weights':{'activity':.75,'location':.25,'maps':.15}}
    diagnostics={'origin_access_options':len(area.get('origin_access',{}).get('options',[])),'origin_access_checked':bool(area.get('origin_access')),'after_access_and_radius':0,'within_travel_area':0,'within_station_distance':0}
    def candidate_filter(candidate):
        diagnostics['after_access_and_radius']+=1
        geometry=candidate['_geometry']
        if not any(overlap(cached_box(json.dumps(geometry,separators=(',',':'))),b) for b in boxes): return False
        if reachability_relation(geometry,area)=='outside_reachable_area': return False
        diagnostics['within_travel_area']+=1
        candidate['nearest_station']=station_filter.nearest_station(geometry)
        if candidate['nearest_station'] is not None: diagnostics['within_station_distance']+=1
        return candidate['nearest_station'] is not None
    # Rank the complete current candidate pool without paying for Maps lookups.
    ranking_request={**request,'top_n':len(dataset()['features'])}
    result=rec.run(ranking_request,dataset(),use_maps=False,candidate_filter=candidate_filter,keep_geometry=True)
    result['request']=request
    candidates=result['recommendations']
    selection=select_candidates(candidates,state['needs'],previous_result,
        enrich=lambda batch:rec.enrich_maps_candidates(batch,request,use_maps),
        verify=lambda batch,needs:verify_facilities(batch,needs,node_json))
    result.update(selection)
    for p in result['recommendations']:p.pop('_geometry',None)
    result['method']['final_score_formula']='base_score + 0.15 × fraction of requested facilities supported by matched evidence; retain eligible verified places, then check ranked candidates in batches.'
    result['method']['maps_status_note']='Unknown evidence does not satisfy a required facility. Reused evidence is at most six hours old; current travel, access and station filters are always reapplied.'
    result['request']['dialogue_needs']=dict(state['needs'])
    result['diagnostics']=diagnostics
    nearest=min(station_filter.station_data()['features'],key=lambda f:rec.haversine_km(state['latitude'],state['longitude'],f['geometry']['coordinates'][1],f['geometry']['coordinates'][0]))
    diagnostics['nearest_origin_station']={'name':nearest['properties'].get('name'),'distance_km':rec.haversine_km(state['latitude'],state['longitude'],nearest['geometry']['coordinates'][1],nearest['geometry']['coordinates'][0])}
    if selection['facility_verification_warning']:
        result['facility_warning']='Facility verification is temporarily unavailable. Unconfirmed information does not satisfy a requirement.'
    result['travel_time']={'minutes':state['minutes'],'transport':'transit_or_taxi_then_train','departure_time':state['departure_time'],'geojson':area}
    for p in result['recommendations']:
        parts=[f"{LABELS.get(k,k)} score {v['raw_score']:.2f}" for k,v in p['activity_score_breakdown'].items()]
        p['llm_recommendation_reason']='; '.join(parts)+'. '
    return enrich_result(result)


def empty_result_message(result):
    diagnostics=result.get('diagnostics',{})
    if diagnostics.get('origin_access_checked') and diagnostics.get('origin_access_options')==0:
        return 'No station access option was returned within the total journey time for the three stations checked. Both public transport and taxi-time estimates were considered. The origin is not subject to a 2 km station-distance rule. Try a longer total journey time or another origin.',[]
    if diagnostics.get('within_travel_area')==0:
        nearest=diagnostics.get('nearest_origin_station')
        answer='No green spaces in this dataset overlap the returned travel area after public-transport or taxi access to a station, followed by train and walking. Facility requirements have not been checked because there were no reachable candidates. You can try a longer total journey time or a different origin.'
        if nearest: answer+=f" The nearest station in our dataset is {nearest['name']}, about {nearest['distance_km']:.1f} km from your origin in a straight line."
        return answer,[]
    if diagnostics.get('within_station_distance')==0:
        return 'Reachable green spaces were found, but none has a station within 2 km of its boundary. Facility requirements have not been checked.',[]
    required=[LABELS.get(k,k) for k,v in result.get('request',{}).get('dialogue_needs',{}).items() if v=='required']
    answer="We could not confirm all required facilities among the places checked"
    if required: answer+=' ('+', '.join(required)+')'
    answer+='. Try a longer travel time or adjust your facility requirements.'
    return answer,['Make toilets a preference, not a requirement'] if 'Toilets' in required else []


def explain(intent, session):
    items=(session.get('last_result') or {}).get('recommendations',[])
    n=intent.get('target')
    if not isinstance(n,int) or isinstance(n,bool) or not 1<=n<=len(items): return 'Which green space do you mean? Give its name or number in the previous recommendations.'
    p=items[n-1]; topic=intent.get('topic','reason')
    if topic=='distance': return f"{p['name']}: The station distance is measured in a straight line to the green-space boundary, not along a walking route. The entrance has not been verified."
    if topic=='access':
        access=p.get('access')
        return f"{p['name']}: The recorded access value is {access}. Check the place information for specific access conditions." if access else f"{p['name']}: Access permission is not recorded, so public access cannot be confirmed."
    if topic=='facilities':
        facts=[f"{LABELS[k]}: "+({'yes':'Supported by evidence','no':'Evidence of unavailability','unknown':'Not confirmed'}[v['status']])+(f" ({v['quote']})" if v['quote'] else '') for k,v in p.get('facility_evidence',{}).items()]
        return p['name']+': '+('; '.join(facts) if facts else 'No facility evidence was checked in the previous search. Tell me which facilities matter.')
    needs=(session.get('last_result_state') or {}).get('needs') or (session.get('last_result') or {}).get('request',{}).get('dialogue_needs',{})
    if not p.get('visitor_reviews',{}).get('review_summary_requested'):
        p['visitor_reviews']=fetch_reviews(p,list(p.get('activity_score_breakdown',{}))+list(needs))
    return explain_fit(p,needs)


def export_markdown(session):
    def cell(s): return str(s).replace('|','\\|').replace('\n','<br>')
    lines=['# Green-space conversation record','','| Turn | Role | Type / skill | Content | Screenshot | Notes |','|---|---|---|---|---|---|']
    for t in session['turns']:
        for role,content in [('User',t['user']),('Assistant',t['assistant'])]:
            lines.append(f"| {t['round']} | {role} | {cell(t['skill'])} | {cell(content)} | To add | {cell(t['timestamp']+'; '+state_summary(t['state']))} |")
        for i,p in enumerate((t.get('result') or {}).get('recommendations',[]),1):
            lines.append(f"| {t['round']} | Result card {i} | Recommendation | {cell(p['name']+'; '+p.get('llm_recommendation_reason','')+'; Station: '+p['nearest_station']['name']+'; Boundary distance: '+str(round(p['nearest_station']['boundary_distance_km'],3))+' km; Facility evidence: '+json.dumps(p.get('facility_evidence',{}),ensure_ascii=False))} | To add | Actual returned result |")
    return '\n'.join(lines)


def handle(payload, invoke=None, recommender=None):
    from recommendation_web_demo import CITIES,node_json
    invoke=invoke or node_json; recommender=recommender or recommend
    with LOCK:
        session=read_session(payload['session_id']) if payload.get('session_id') else new_session()
        command=payload.get('command','message')
        if command in {'load','export'}:
            enrich_result(session['last_result'])
            for turn in session['turns']: enrich_result(turn.get('result'))
            return {'session_id':session['id'],'state':session['state'],'turns':session['turns'],'result':session['last_result'],'markdown':export_markdown(session)}
        message=str(payload.get('message','')).strip()
        if not message or len(message)>2000: raise ValueError('Please enter a message of 1–2000 characters.')
        if len(session['turns'])>=100: raise ValueError('This conversation has reached 100 turns. Export it and start a new one.')
        state=apply_ui(session['state'],payload.get('ui',{}),CITIES)
        if not state['departure_time'] or dt.datetime.fromisoformat(state['departure_time'].replace('Z','+00:00')) <= dt.datetime.now(dt.timezone.utc):
            state['departure_time']=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).replace(hour=9,minute=0,second=0,microsecond=0).isoformat()
        before=copy.deepcopy(state); result=None; suggestions=[]; skill='clarify'; error=None; evidence_candidate=None; intent={}
        try:
            intent=invoke('dialogue_llm.mjs',{'mode':'intent','message':message,'state':state,'pending':session['pending'],'cities':list(CITIES),'last_recommendations':[p['name'] for p in (session['last_result'] or {}).get('recommendations',[])],'recent_turns':[{'user':t['user'],'assistant':t['assistant']} for t in session['turns'][-6:]]})
            intent=normalize_activity_intent(message,intent,state)
            intent=normalize_followup(message,intent,state,session)
            action=intent.get('action')
            if action not in {'recommend','clarify','dissatisfied','explain','review_evidence','boundary','reset'}: raise ValueError('Unable to determine the next action. Please rephrase.')
            state=validate_patch(state,intent.get('patch',{}),CITIES)
            # An answered activity preference should not trigger another yes/no gate.
            if action=='clarify' and state['latitude'] is not None and state['minutes'] is not None and state['activities'] and intent.get('patch',{}).get('activities') and re.search(r'prioriti[sz]e|confirm|is that (right|correct)',str(intent.get('question','')),re.I):
                action='recommend'
            # Origin coordinates are authoritative; do not ask for a city name
            # solely because a dragged point has no city label.
            question=str(intent.get('question',''))
            if action=='clarify' and state['latitude'] is not None and state['longitude'] is not None and state['activities'] and re.search(r'(which|what).*(city|origin|start)|where.*(start|from)',question,re.I) and not re.search(r'destination|or.*from|instead',question,re.I):
                action='recommend'
            skill=action
            if action=='reset':
                state=new_session()['state']; session['last_result']=None; session['last_result_state']=None
                session.pop('last_explained_key',None);session.pop('pending_review_topics',None)
                answer='Preferences cleared. Choose or describe your origin, travel limit and activities.'; session['pending']=answer
            elif action in {'clarify','dissatisfied'}:
                answer='What would you like to change: travel time, activities, or facilities?' if action=='dissatisfied' else str(intent.get('question') or 'Please tell me which preferences you would like to change.')[:500]
                session['pending']=answer
            elif action=='review_evidence':
                index=review_target(message,intent,session)
                topics=intent.get('review_topics') or session.get('pending_review_topics',[])
                if index is None:
                    answer='Which green space should I check the visitor feedback for? Please give its name or number.'
                    skill='clarify';session['pending']=answer;session['pending_review_topics']=topics
                else:
                    p=session['last_result']['recommendations'][index-1]
                    answer=answer_review_followup(p,topics,invoke)
                    evidence_candidate=copy.deepcopy(p);evidence_candidate['display_rank']=index
                    session['last_explained_key']=candidate_key(p)
                    session['pending']=None;session.pop('pending_review_topics',None)
            elif action=='explain':
                answer=explain(intent,session); session['pending']=answer if not intent.get('target') else None
                index=intent.get('target')
                items=(session.get('last_result') or {}).get('recommendations',[])
                if isinstance(index,int) and not isinstance(index,bool) and 1<=index<=len(items):
                    enrich_result(session['last_result'])
                    evidence_candidate=copy.deepcopy(items[index-1]); evidence_candidate['display_rank']=index
                    session['last_explained_key']=candidate_key(items[index-1])
            else:
                missing=[]
                if state['latitude'] is None: missing.append('your origin city or map location')
                if state['minutes'] is None: missing.append('your maximum travel time')
                if not state['activities']: missing.append('your activities, such as birdwatching, walking or nature')
                unsupported=intent.get('unsupported',[])
                if not isinstance(unsupported,list): unsupported=[]
                prefix=('I cannot reliably verify or filter for: '+', '.join(str(x)[:100] for x in unsupported[:5])+'. \n') if unsupported else ''
                if missing:
                    answer=prefix+'Please provide '+ ', '.join(missing)+'. '; session['pending']=answer; skill='clarify'
                elif action=='boundary' and state==before:
                    answer=prefix+'Your current preferences remain in place. Other scores will not be used as a substitute.'; session['pending']=None
                elif state==before and session.get('last_result') and 'BR-03 playground cancellation is independent' in intent.get('policy_notes',[]):
                    skill='preferences'
                    answer='Playground is not an active requirement. Your other preferences remain in place. Current preferences: '+state_summary(state)+'.'
                    session['pending']=None
                else:
                    skill='refine' if session['last_result'] else 'recommend'
                    result=recommender(state,True,previous_result=session.get('last_result')) if recommender is recommend else recommender(state,True)
                    session['last_result']=result; session['last_result_state']=copy.deepcopy(state); session['pending']=None
                    session.pop('last_explained_key',None);session.pop('pending_review_topics',None)
                    count=len(result['recommendations'])
                    answer=prefix+'Current preferences: '+state_summary(state)+'. \n\n'
                    if count:
                        answer+=f'Here are {count} recommended green spaces.'
                    else:
                        explanation,suggestions=empty_result_message(result)
                        answer+=explanation
                    if 'family_friendly' in state['needs']:
                        answer+='\nTravelling with children? Add an optional preference below, or keep the current results.'
                        suggestions+=['Suitable for a pushchair','Toilets are required']
                    if result.get('facility_warning'): answer+='\n'+result['facility_warning']
        except Exception as exc:
            logging.exception('Dialogue turn failed')
            error=type(exc).__name__
            answer='This request could not be completed. Your preferences and conversation are saved. Please retry; no new recommendations were generated.'
            if '429' in str(exc): answer='An external service is temporarily rate-limited. Please retry shortly. Your preferences and conversation are saved; no new recommendations were generated.'
            skill='service_error'; session['pending']=answer
        session['state']=state
        turn={'round':len(session['turns'])+1,'timestamp':dt.datetime.now(dt.timezone.utc).isoformat(),'user':message,'assistant':answer,'skill':skill,'state':copy.deepcopy(state),'result':result,'suggestions':list(dict.fromkeys(suggestions)),'evidence_candidate':evidence_candidate,'error':error,'policy_notes':intent.get('policy_notes',[])}
        session['turns'].append(turn); save_session(session)
        return {'session_id':session['id'],'state':state,'turn':turn,'result':result,'clear_results':skill=='reset'}
