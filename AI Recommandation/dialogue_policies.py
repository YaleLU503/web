"""Explicit state-update and evidence-routing rules for follow-up messages."""
import copy
import re
from facility_search import candidate_key

TOPICS = {
    'quietness': r'\bquiet\b|\bpeaceful\b|\btranquil\b|\bserene\b|\bnoisy\b|安静|宁静|清静|吵闹',
    'crowding': r'\bcrowd\w*\b|\bbusy\b|few(?:er)? people|人少|人多|拥挤|人流',
}
CHILDREN_CANCEL = r"\b(?:not|no longer)\s+(?:bringing|taking|travelling with|traveling with)\s+(?:(?:my|the|our|any)\s+)?(?:kids|children)\b|\bwithout\s+(?:(?:my|the|our|any)\s+)?(?:kids|children)\b|\b(?:kids|children)\s+(?:are not|aren't|won't be)\s+(?:coming|joining)\b|不带(?:小孩|孩子|儿童)|(?:孩子|小孩)不(?:来|去|同行)"
FAMILY_CANCEL = r"\b(?:family[- ]friendly|family friendliness|child[- ]friendly)\b.{0,30}(?:no longer|not|doesn't|does not).{0,15}(?:important|matter|need|required)|\b(?:remove|drop|cancel)\b.{0,15}\bfamily[- ]friendly\b|(?:不需要|不考虑|取消)亲子|亲子.{0,8}(?:不重要|不需要)"
PLAYGROUND_CANCEL = r"\bplayground\b.{0,25}(?:no longer|not|isn't|doesn't|does not).{0,15}(?:important|matter|need|required)|\b(?:remove|drop|cancel|without|don't need|do not need)\s+(?:the |a |any )?playground\b|(?:不需要|不要|取消|不考虑)(?:儿童)?游乐场|游乐场.{0,8}(?:不重要|不需要)"


def normalize_followup(message, intent, state, session):
    intent = copy.deepcopy(intent)
    if intent.get('action') == 'reset':
        return intent
    patch = intent.setdefault('patch', {})
    if not isinstance(patch, dict):
        return intent
    needs = patch.setdefault('needs', {})
    party = patch.setdefault('travel_party', {})
    if not isinstance(needs, dict) or not isinstance(party, dict):
        return intent
    child_cancel = bool(re.search(CHILDREN_CANCEL, message, re.I))
    family_cancel = child_cancel or bool(re.search(FAMILY_CANCEL, message, re.I))
    playground_cancel = bool(re.search(PLAYGROUND_CANCEL, message, re.I))
    if needs.get('family_friendly') == 'remove' and not family_cancel:
        needs.pop('family_friendly')
        intent.setdefault('policy_notes', []).append('BR-02 blocked unsupported family preference removal')
    if party.get('children') is False and not child_cancel:
        party.pop('children')
    if child_cancel:
        party['children'] = False
        needs['family_friendly'] = 'remove'
    elif re.search(r'\b(?:with|bringing|taking)\s+(?:(?:my|our|the)\s+)?(?:kids|children)\b|带(?:着)?(?:孩子|小孩|儿童)', message, re.I):
        party['children'] = True
    if playground_cancel:
        needs['playground'] = 'remove'
        if intent.get('action') in {'boundary','clarify'}:
            intent['action']='recommend'
        intent.setdefault('policy_notes', []).append('BR-03 playground cancellation is independent')
    if not needs:
        patch.pop('needs', None)
    if not party:
        patch.pop('travel_party', None)
    topics = [key for key, pattern in TOPICS.items() if re.search(pattern, message, re.I)]
    if not topics:
        topics = [key for key in intent.get('review_topics', []) if key in TOPICS]
    if not topics and session.get('pending_review_topics') and intent.get('action') in {'explain','review_evidence','clarify'}:
        topics = session['pending_review_topics']
    # Route subjective follow-ups before the unsupported-demand branch, without
    # discarding a simultaneous change to trip conditions.
    changed = any(value != state.get(key) for key, value in patch.items() if key not in {'needs', 'travel_party'})
    changed = changed or any((key in state.get('needs',{}) if value=='remove' else value!=state.get('needs',{}).get(key)) for key,value in patch.get('needs',{}).items())
    changed = changed or any(value!=state.get('travel_party',{}).get(key) for key,value in patch.get('travel_party',{}).items())
    if topics and (session.get('last_result') or {}).get('recommendations') and not changed:
        intent['action'] = 'review_evidence'
        intent['review_topics'] = topics
        intent['unsupported'] = []
    return intent


def review_target(message, intent, session):
    items = (session.get('last_result') or {}).get('recommendations', [])
    named = [i for i, p in enumerate(items, 1) if p['name'].casefold() in message.casefold()]
    if len(named) == 1:
        return named[0]
    for pattern, index in [(r'\bfirst\b|第一个|第一名', 1), (r'\bsecond\b|第二个|第二名', 2), (r'\bthird\b|第三个|第三名', 3)]:
        if re.search(pattern, message, re.I):
            return index if index <= len(items) else None
    numeric = re.search(r'(?:place|number|candidate|#)\s*(\d+)|第\s*(\d+)\s*(?:个|名)', message, re.I)
    if numeric:
        index = int(numeric.group(1) or numeric.group(2))
        return index if 1 <= index <= len(items) else None
    key = session.get('last_explained_key')
    if not key:
        for turn in reversed(session.get('turns', [])):
            if turn.get('evidence_candidate'):
                key = candidate_key(turn['evidence_candidate'])
                break
            if turn.get('result'):
                break
    matched = [i for i, p in enumerate(items, 1) if candidate_key(p) == key]
    return matched[0] if len(matched) == 1 else 1 if len(items) == 1 else None
