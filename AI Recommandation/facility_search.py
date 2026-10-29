"""Reuse recent place evidence and check ranked candidates within a fixed budget."""
import copy
import datetime as dt
import json
import logging

NEW_CHECK_LIMIT = 20
CACHE_MAX_AGE = dt.timedelta(hours=6)
EVIDENCE_FIELDS = ('maps_grounding', 'maps_entity_match', 'maps_need_status',
                   'maps_score', 'facility_evidence', 'visitor_reviews')


def candidate_key(candidate):
    centre = candidate.get('geometry_center', {})
    return json.dumps([candidate.get('place_id'), candidate.get('name'),
                       centre.get('latitude'), centre.get('longitude')], separators=(',', ':'))


def select_candidates(candidates, needs, previous, enrich, verify, limit=NEW_CHECK_LIMIT,
                      target=5, now=None):
    """All input candidates have passed the CURRENT spatial and access filters.

    The budget counts new candidate checks, not reused evidence. Cached negative
    or unknown findings never satisfy a required facility.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    cache = copy.deepcopy((previous or {}).get('facility_evidence_cache', {}))
    # Existing conversations already contain verified recommendations from the
    # previous implementation. Seed their evidence without another API call.
    for p in (previous or {}).get('recommendations', []):
        key = candidate_key(p)
        stamp = p.get('maps_grounding', {}).get('retrieved_at') or (previous or {}).get('generated_at')
        if key not in cache and stamp and 'facility_evidence' in p:
            cache[key] = {'verified_at': stamp, 'checked_needs': list(p['facility_evidence']),
                          'evidence': {k: copy.deepcopy(p[k]) for k in EVIDENCE_FIELDS if k in p}}
    by_key = {candidate_key(p): p for p in candidates}
    required = [k for k, priority in needs.items() if priority == 'required']
    checked, matches = set(), []
    warning = False

    def qualifies(p):
        return all(p.get('facility_evidence', {}).get(k, {}).get('status') == 'yes' for k in required)

    def score(p):
        facts = p.get('facility_evidence', {})
        p['final_score'] = p['base_score'] + .15 * (sum(facts.get(k, {}).get('status') == 'yes' for k in needs) / len(needs) if needs else 0)

    # Keep previous recommendations first, then consider other reusable checks.
    prior_keys = [candidate_key(p) for p in (previous or {}).get('recommendations', [])]
    ordered_keys = list(dict.fromkeys(prior_keys + list(by_key)))
    for key in ordered_keys:
        if key not in by_key:
            continue
        entry = cache.get(key, {})
        try:
            age = now - dt.datetime.fromisoformat(entry['verified_at'])
        except (KeyError, TypeError, ValueError):
            continue
        evidence = entry.get('evidence', {})
        if not dt.timedelta(0) <= age <= CACHE_MAX_AGE or not set(needs).issubset(entry.get('checked_needs', [])):
            continue
        if evidence.get('maps_grounding', {}).get('status') != 'ok':
            continue
        candidate = by_key[key]
        candidate.update(copy.deepcopy(evidence))
        candidate['facility_evidence'] = {k: candidate.get('facility_evidence', {}).get(k, {'status': 'unknown', 'quote': ''}) for k in needs}
        score(candidate)
        checked.add(key)
        if qualifies(candidate):
            matches.append(candidate)
    reused_count = len(checked)
    cached_matching_count = len(matches)
    # Do not displace already-confirmed places merely because the search grew.
    retained_matches = matches[:target]
    matches = list(retained_matches)
    pending = [p for p in candidates if candidate_key(p) not in checked]
    new_count, offset = 0, 0
    while len(matches) < target and offset < len(pending) and new_count < limit:
        size = min(5, target - len(matches), limit - new_count, len(pending) - offset)
        batch = pending[offset:offset + size]
        offset += size
        verified = True
        try:
            enrich(batch)
            result = {'recommendations': batch}
            verify(result, needs)
        except Exception as exc:
            logging.warning('Facility candidate batch failed (%s)', type(exc).__name__)
            verified = False
            warning = True
            # A partial extraction failure must not manufacture affirmative facts.
            result = {'recommendations': batch}
            for p in batch:
                p['facility_evidence'] = {k: {'status': 'unknown', 'quote': ''} for k in needs}
        for p in batch:
            key = candidate_key(p)
            checked.add(key)
            score(p)
            if qualifies(p):
                matches.append(p)
            if verified and p.get('maps_grounding', {}).get('status') == 'ok':
                cache[key] = {'verified_at': now.isoformat(), 'checked_needs': list(needs),
                              'evidence': {k: copy.deepcopy(p[k]) for k in EVIDENCE_FIELDS if k in p}}
        new_count += size
    matches.sort(key=lambda p: (-p['final_score'], p.get('distance_km', 0), p.get('name') or ''))
    return {
        'recommendations': matches[:target],
        'facility_evidence_cache': cache,
        'checked_candidate_count': len(checked),
        'newly_checked_candidate_count': new_count,
        'reused_candidate_count': reused_count,
        'retained_candidate_count': len(retained_matches),
        'matching_checked_count': cached_matching_count + len(matches) - len(retained_matches),
        'unchecked_candidate_count': len(candidates) - len(checked),
        'facility_new_check_limit': limit,
        'facility_check_limit_reached': new_count >= limit and len(matches) < target and len(checked) < len(candidates),
        'facility_verification_warning': warning,
    }


def coverage_message(result):
    checked = result.get('checked_candidate_count', 0)
    reused = result.get('reused_candidate_count', 0)
    new = result.get('newly_checked_candidate_count', checked)
    remaining = result.get('unchecked_candidate_count', 0)
    text = f'Facility evidence checked for {checked} candidates: {reused} reused and {new} newly checked. '
    text += f"{result.get('retained_candidate_count', 0)} previously checked candidates retained. "
    text += f'{remaining} candidates remain unchecked. '
    text += f"Limit: {result.get('facility_new_check_limit', NEW_CHECK_LIMIT)} new candidate checks per search."
    if result.get('facility_check_limit_reached'):
        text += ' The check limit was reached; more matching places may exist among unchecked candidates.'
    return text
