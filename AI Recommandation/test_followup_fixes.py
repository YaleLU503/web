import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import dialogue_service as service
from dialogue_policies import normalize_followup, review_target
from facility_search import candidate_key
from review_followup import answer_review_followup


def place():
    return {'name':'Bushy Park and Home Park','place_id':218,'activity_score_breakdown':{},
        'visitor_reviews':{'status':'ok','scope':'geographic_alias','place_name':'Bushy Park',
            'review_summary_requested':True,'retrieved_at':'2026-10-22T12:00:00+00:00',
            'review_summary':{'text':{'text':'Visitors enjoy the peaceful atmosphere. It gets crowded on weekends.'},
                'disclosureText':{'text':'Summarized with Gemini'},'reviewsUri':'https://example.com/reviews'}}}


class FollowupFixTests(unittest.TestCase):
    def setUp(self):
        self.state={'needs':{'family_friendly':'preferred','toilets':'required','playground':'preferred'},
                    'activities':{'nature':3,'hiking':3},'travel_party':{'children':True}}
    def test_playground_cancellation_cannot_delete_children_or_family(self):
        for text in ['A playground is no longer important, but please keep the walking and toilet requirements.', '游乐场不重要了，但保留步行和厕所要求。']:
            intent=normalize_followup(text,{'action':'recommend','patch':{'needs':{'family_friendly':'remove'},'travel_party':{'children':False}}},self.state,{})
            self.assertNotIn('family_friendly',intent['patch']['needs'])
            self.assertEqual(intent['patch']['needs']['playground'],'remove')
            self.assertNotIn('children',intent['patch'].get('travel_party',{}))
    def test_explicit_child_withdrawal_still_works(self):
        for text in ['I am no longer bringing my kids.', '不带孩子了']:
            intent=normalize_followup(text,{'action':'recommend','patch':{}},self.state,{})
            self.assertFalse(intent['patch']['travel_party']['children'])
            self.assertEqual(intent['patch']['needs']['family_friendly'],'remove')
    def test_child_party_is_separate_from_family_suitability(self):
        intent=normalize_followup('Family-friendly is no longer important.',{'action':'recommend','patch':{'needs':{'family_friendly':'remove'}}},self.state,{})
        self.assertEqual(intent['patch']['needs']['family_friendly'],'remove')
        self.assertNotIn('travel_party',intent['patch'])
    def test_do_not_need_playground_for_children_does_not_cancel_children(self):
        intent=normalize_followup("I don't need a playground for my children.",{'action':'recommend','patch':{'needs':{'family_friendly':'remove'}}},self.state,{})
        self.assertNotIn('family_friendly',intent['patch']['needs'])
    def test_boundary_rerouted_to_reviews_with_last_place(self):
        p=place();session={'last_result':{'recommendations':[p]},'last_explained_key':candidate_key(p)}
        intent=normalize_followup('We prefer somewhere quiet and less crowded. Do the visitor reviews support that?',{'action':'boundary','patch':{}},self.state,session)
        self.assertEqual(intent['action'],'review_evidence')
        self.assertEqual(intent['review_topics'],['quietness','crowding'])
        self.assertEqual(review_target('',intent,session),1)
    def test_explicit_second_place_overrides_previous_focus(self):
        a=place();b={**place(),'place_id':20,'name':'Another Park'}
        s={'last_result':{'recommendations':[a,b]},'last_explained_key':candidate_key(a)}
        self.assertEqual(review_target('Is the second place quiet?',{},s),2)
    def test_ambiguous_multiple_places_need_clarification(self):
        s={'last_result':{'recommendations':[place(),{**place(),'place_id':20,'name':'Another Park'}]}}
        self.assertIsNone(review_target('Is it quiet?',{'target':1},s))
    def test_review_does_not_swallow_time_change(self):
        s={'last_result':{'recommendations':[place()]}}
        i=normalize_followup('Increase to 120 minutes, somewhere quiet.',{'action':'recommend','patch':{'minutes':120}},self.state,s)
        self.assertEqual(i['action'],'recommend')
    def test_existing_summary_is_reused_and_negative_feedback_preserved(self):
        p=place()
        extraction={'evidence':{'quietness':{'status':'supported','quotes':['Visitors enjoy the peaceful atmosphere.']},'crowding':{'status':'opposed','quotes':['It gets crowded on weekends.']}}}
        with patch('review_followup.fetch_reviews') as fetch:
            answer=answer_review_followup(p,['quietness','crowding'],lambda *a:extraction)
        fetch.assert_not_called()
        self.assertIn('descriptions against',answer)
        self.assertIn('Summarized with Gemini',answer)
        self.assertIn('https://example.com/reviews',answer)
        self.assertTrue(p['review_followup']['reused'])
    def test_quiet_quote_cannot_establish_low_crowding(self):
        p=place()
        answer_review_followup(p,['crowding'],lambda *a:{'evidence':{'crowding':{'status':'supported','quotes':['Visitors enjoy the peaceful atmosphere.']}}})
        self.assertEqual(p['review_followup']['evidence']['crowding']['status'],'unknown')
    def test_invented_quote_is_rejected(self):
        p=place()
        answer_review_followup(p,['quietness'],lambda *a:{'evidence':{'quietness':{'status':'supported','quotes':['This park is quiet every day.']}}})
        self.assertEqual(p['review_followup']['evidence']['quietness']['status'],'unknown')
    def test_absent_summary_triggers_fetch_and_stays_unknown_if_missing(self):
        p=place();p.pop('visitor_reviews')
        with patch('review_followup.fetch_reviews',return_value={'status':'ok','review_summary_requested':True}) as fetch:
            answer=answer_review_followup(p,['quietness'],lambda *a:self.fail('No summary to interpret'))
        fetch.assert_called_once()
        self.assertIn('No attributable',answer)
    def test_interpretation_failure_keeps_source_and_does_not_invent(self):
        def fail(*a):raise TimeoutError()
        p=place();answer=answer_review_followup(p,['quietness'],fail)
        self.assertIn('temporarily unavailable',answer)
        self.assertIn('peaceful atmosphere',answer)
        self.assertEqual(p['review_followup']['evidence']['quietness']['status'],'unknown')
    def test_handle_persists_guarded_state_and_independent_playground_removal(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(service,'DB_PATH',Path(folder)/'test.sqlite3'):
            s=service.new_session();s['state'].update(self.state,city='London',latitude=51.5,longitude=-.1,minutes=90)
            service.save_session(s)
            result=service.handle({'session_id':s['id'],'message':'A playground is no longer important, but please keep the walking and toilet requirements.'},
                invoke=lambda *a:{'action':'recommend','patch':{'needs':{'family_friendly':'remove'}}},
                recommender=lambda *a:{'recommendations':[],'candidate_count_after_filters':0})
            state=result['state']
            self.assertEqual(state['needs'],{'family_friendly':'preferred','toilets':'required'})
            self.assertTrue(state['travel_party']['children'])
            self.assertEqual(service.read_session(s['id'])['state'],state)


if __name__=='__main__':unittest.main()
