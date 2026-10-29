"""Answer experience follow-ups from attributable review evidence."""
import re
from visitor_reviews import fetch_reviews

LABELS = {'quietness': 'Quiet atmosphere', 'crowding': 'Fewer crowds'}
RELEVANT = {'quietness': r'quiet|peace|seren|tranquil|nois|calm|loud',
            'crowding': r'crowd|busy|packed|queue|empty|few(?:er)?\s+(?:people|visitors)|not many\s+(?:people|visitors)'}


def answer_review_followup(candidate, topics, invoke):
    topics = [key for key in topics if key in LABELS]
    if not topics:
        return 'Which aspect of the visitor feedback would you like to check: quietness or crowding?'
    reviews = candidate.get('visitor_reviews') or {}
    reused = bool(reviews.get('status') == 'ok' and reviews.get('review_summary', {}).get('text', {}).get('text'))
    if not reused and (not reviews.get('review_summary_requested') or reviews.get('status') != 'ok'):
        reviews = fetch_reviews(candidate, list(candidate.get('activity_score_breakdown', {})) + topics)
        candidate['visitor_reviews'] = reviews
    summary = reviews.get('review_summary') or {}
    text = summary.get('text', {}).get('text', '')
    usable = (reviews.get('status') == 'ok' and text and summary.get('reviewsUri')
              and summary.get('disclosureText', {}).get('text')
              and reviews.get('scope') in {'matched_place', 'geographic_alias', 'component_only'})
    evidence = {key: {'status': 'unknown', 'quotes': []} for key in topics}
    extraction_error = False
    if usable:
        try:
            data = invoke('dialogue_llm.mjs', {'mode': 'review_evidence', 'topics': topics,
                          'place_name': reviews.get('place_name', candidate['name']), 'summary': text})
            for key in topics:
                item = data.get('evidence', {}).get(key, {})
                quotes = item.get('quotes', [])
                if not isinstance(quotes, list):
                    continue
                quotes = [q for q in quotes[:3] if isinstance(q, str) and len(q.strip()) >= 8 and q in text and re.search(RELEVANT[key], q, re.I)]
                status = item.get('status')
                if quotes and status in {'supported', 'opposed', 'mixed'}:
                    evidence[key] = {'status': status, 'quotes': quotes}
        except Exception:
            extraction_error = True
    candidate['review_followup'] = {'topics': topics, 'evidence': evidence,
        'source_type': 'google_review_summary', 'source_place': reviews.get('place_name'),
        'source_url': summary.get('reviewsUri'), 'retrieved_at': reviews.get('retrieved_at'),
        'reused': reused, 'extraction_error': extraction_error, 'reranked': False}
    lines = [f"Visitor feedback for {candidate['name']}:"]
    for key, item in evidence.items():
        wording = {'supported': 'The review summary contains supporting descriptions.',
                   'opposed': 'The review summary contains descriptions against this preference.',
                   'mixed': 'The review summary contains mixed or conditional descriptions.',
                   'unknown': 'This preference is not established by the available review evidence.'}[item['status']]
        lines.append(LABELS[key] + ': ' + wording)
    if usable:
        lines.append('Google review summary for ' + reviews.get('place_name', candidate['name']) + ': ' + text)
        lines.append(summary['disclosureText']['text'])
        lines.append('Read reviews on Google Maps: ' + summary['reviewsUri'])
        if summary.get('flagContentUri'):
            lines.append('Report this summary: ' + summary['flagContentUri'])
        if reviews.get('retrieved_at'):
            lines.append('Evidence retrieved: ' + reviews['retrieved_at'])
        if reviews.get('scope') == 'component_only':
            lines.append('These comments concern that named component only, not the entire combined green space.')
        elif reviews.get('scope') == 'geographic_alias':
            lines.append('The source is the geographically matched Google place; conditions can vary across the green space.')
    else:
        lines.append('No attributable Google review summary was available for this place. No conclusion about quietness or crowding has been inferred.')
    if extraction_error:
        lines.append('The review interpretation service is temporarily unavailable; the original summary is shown for reference.')
    lines.append('A peaceful atmosphere does not establish low visitor numbers. Reviews cannot guarantee current or future crowd levels. This evidence follow-up does not change the ranking or your trip requirements.')
    return '\n'.join(lines)
