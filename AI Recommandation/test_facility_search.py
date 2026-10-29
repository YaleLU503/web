import copy
import datetime as dt
import unittest
from unittest.mock import patch
import recommend_demo as rec
from facility_search import select_candidates, candidate_key, coverage_message


class FacilitySearchTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 22, 12, tzinfo=dt.timezone.utc)
        self.calls = []

    def place(self, index, status='unknown'):
        return {'place_id': index, 'name': f'Park {index}', 'base_score': 1-index/100,
                'distance_km': index, 'maps_grounding': {'status': 'ok', 'summary': 'Public toilets are available.', 'retrieved_at': self.now.isoformat()},
                'maps_entity_match': {'status': 'related_named_place'},
                'facility_evidence': {'toilets': {'status': status, 'quote': 'Public toilets are available.' if status == 'yes' else ''}}}

    def search(self, places, previous=None, good=(), limit=20, needs=None, enrich=None):
        def fetch(batch):
            self.calls.extend(p['place_id'] for p in batch)
        def verify(result, needs):
            for p in result['recommendations']:
                p['facility_evidence'] = {k: {'status': 'yes' if p['place_id'] in good else 'unknown', 'quote': 'Public toilets are available.'} for k in needs}
        return select_candidates(copy.deepcopy(places), needs or {'toilets': 'required'}, previous,
                                 enrich or fetch, verify, limit=limit, now=self.now)

    def test_expansion_keeps_three_verified_places_and_searches_beyond_top_five(self):
        previous = {'recommendations': [self.place(i, 'yes') for i in [8, 9, 10]]}
        result = self.search([self.place(i) for i in range(15)], previous, good={6, 7})
        self.assertEqual({p['place_id'] for p in result['recommendations']}, {6, 7, 8, 9, 10})
        self.assertEqual(result['retained_candidate_count'], 3)
        self.assertEqual(result['newly_checked_candidate_count'], 8)
        self.assertFalse({8, 9, 10}.intersection(self.calls))

    def test_prior_place_must_still_pass_current_filters(self):
        result = self.search([self.place(i) for i in range(7)], {'recommendations': [self.place(99, 'yes')]}, good={0, 1, 2, 3, 4})
        self.assertNotIn(99, [p['place_id'] for p in result['recommendations']])
        self.assertEqual(result['retained_candidate_count'], 0)

    def test_expired_evidence_is_checked_again(self):
        p = self.place(0, 'yes')
        p['maps_grounding']['retrieved_at'] = (self.now-dt.timedelta(hours=7)).isoformat()
        result = self.search([self.place(0)], {'recommendations': [p]})
        self.assertEqual(self.calls, [0])
        self.assertEqual(result['recommendations'], [])

    def test_new_required_facility_cannot_reuse_unchecked_fact(self):
        result = self.search([self.place(0)], {'recommendations': [self.place(0, 'yes')]}, needs={'toilets': 'required', 'pet_friendly': 'required'})
        self.assertEqual(self.calls, [0])
        self.assertEqual(result['recommendations'], [])

    def test_unknown_and_negative_are_not_confirmed(self):
        previous = {'recommendations': [self.place(0, 'unknown'), self.place(1, 'no')]}
        result = self.search([self.place(i) for i in range(4)], previous)
        self.assertEqual(result['recommendations'], [])
        self.assertEqual(result['reused_candidate_count'], 2)
        self.assertEqual(self.calls, [2, 3])

    def test_limit_stops_checks_and_reports_unchecked_candidates(self):
        result = self.search([self.place(i) for i in range(30)], limit=20)
        self.assertEqual(len(self.calls), 20)
        self.assertEqual(result['unchecked_candidate_count'], 10)
        self.assertTrue(result['facility_check_limit_reached'])
        self.assertIn('limit was reached', coverage_message(result))

    def test_exhaustion_is_distinct_from_budget_stop(self):
        result = self.search([self.place(i) for i in range(3)])
        self.assertEqual(result['unchecked_candidate_count'], 0)
        self.assertFalse(result['facility_check_limit_reached'])

    def test_five_retained_places_need_no_new_calls(self):
        previous = {'recommendations': [self.place(i, 'yes') for i in range(10, 15)]}
        result = self.search([self.place(i) for i in range(20)], previous)
        self.assertEqual(self.calls, [])
        self.assertEqual(result['newly_checked_candidate_count'], 0)
        self.assertEqual(len(result['recommendations']), 5)

    def test_failed_extraction_is_not_cached_as_success(self):
        def fail(batch):
            raise TimeoutError()
        result = self.search([self.place(i, 'yes') for i in range(3)], enrich=fail)
        self.assertEqual(result['recommendations'], [])
        self.assertTrue(result['facility_verification_warning'])
        self.assertEqual(result['facility_evidence_cache'], {})

    def test_duplicate_names_do_not_share_evidence(self):
        old = self.place(1, 'yes')
        new = self.place(2)
        old['name'] = new['name'] = 'Same Park'
        self.assertNotEqual(candidate_key(old), candidate_key(new))
        result = self.search([new], {'recommendations': [old]})
        self.assertEqual(result['recommendations'], [])

    def test_cache_survives_turn_and_reuses_negative_results(self):
        first = self.search([self.place(i) for i in range(10)], good={0}, limit=3)
        self.calls.clear()
        second = self.search([self.place(i) for i in range(12)], first, good={3, 4, 5, 6})
        self.assertEqual(second['retained_candidate_count'], 1)
        self.assertEqual(second['reused_candidate_count'], 3)
        self.assertEqual(self.calls, [3, 4, 5, 6])
        self.assertEqual(len(second['recommendations']), 5)

    def test_live_enrichment_path_uses_request_activities(self):
        p = self.place(1)
        request = {'activities': [{'tag': 'hiking', 'weight': 1}], 'maps_needs': [{'tag': 'toilets', 'weight': 1}]}
        response = {'status': 'ok', 'summary': 'Public toilets are available.', 'places': []}
        with patch.object(rec, 'read_env_value', return_value='test-key'), patch.object(rec, 'call_maps_grounding', return_value=response) as lookup:
            rec.enrich_maps_candidates([p], request)
        lookup.assert_called_once()
        self.assertEqual(p['maps_grounding']['summary'], response['summary'])


if __name__ == '__main__':
    unittest.main()
