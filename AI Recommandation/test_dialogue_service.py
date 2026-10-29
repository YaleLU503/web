import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import dialogue_service as d
import recommend_demo as r
import recommendation_web_demo as w

class DialogueTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(d,'DB_PATH',Path(self.tmp.name)/'test.sqlite3');self.patch.start()
  self.ui={'city':'Glasgow','minutes':60,'departure_time':'2026-10-24T09:00:00+01:00'}
  self.calls=[]
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def recommend(self,state,use_maps):
  self.calls.append(copy.deepcopy(state));return {'recommendations':[],'checked_candidate_count':5,'candidate_count_after_filters':20}
 def send(self,text,intent,sid=None,ui=None):
  return d.handle({'message':text,'session_id':sid,'ui':ui or {}},invoke=lambda *args:intent,recommender=self.recommend)
 def test_empty_origin_requires_clarification(self):
  a=self.send('Birdwatching',{'action':'recommend','patch':{'activities':{'birdwatching':1}}},ui={'city':None,'minutes':60})
  self.assertIsNone(a['state']['latitude']);self.assertEqual(a['turn']['skill'],'clarify');self.assertIn('origin',a['turn']['assistant']);self.assertTrue(a['state']['departure_time']);self.assertFalse(self.calls)
 def test_map_origin_without_city(self):
  a=self.send('Birdwatching',{'action':'recommend','patch':{'activities':{'birdwatching':1}}},ui={'latitude':51.5,'longitude':-.1,'minutes':60})
  self.assertEqual(a['state']['latitude'],51.5);self.assertEqual(a['turn']['skill'],'recommend')
 def test_echoed_map_label_keeps_coordinates(self):
  a=self.send('walking with dogs and need wc and good national views',{'action':'recommend','patch':{'city':'Selected map point','activities':{'hiking':1},'needs':{'pet_friendly':'preferred','toilets':'required'}}},ui={'latitude':51.6,'longitude':-.3,'minutes':125})
  self.assertEqual(a['turn']['skill'],'recommend');self.assertEqual(a['state']['latitude'],51.6);self.assertEqual(a['state']['longitude'],-.3);self.assertEqual(a['state']['minutes'],125)
 def test_map_label_without_coordinates_is_rejected(self):
  with self.assertRaises(ValueError):d.validate_patch(d.new_session()['state'],{'city':'Selected map point'},w.CITIES)
 def test_no_reachable_candidates_explains_true_stage(self):
  answer,options=d.empty_result_message({'diagnostics':{'within_travel_area':0,'nearest_origin_station':{'name':'Broughty Ferry','distance_km':3.93}}})
  self.assertIn('have not been checked',answer);self.assertIn('3.9',answer);self.assertEqual(options,[])
 def test_no_station_match_is_distinct(self):
  answer,_=d.empty_result_message({'diagnostics':{'within_travel_area':3,'within_station_distance':0}})
  self.assertIn('none has a station',answer)
 def test_answered_activity_does_not_repeat_confirmation(self):
  a=self.send('natural scenery',{'action':'clarify','question':'Do you want to prioritize natural scenery?','patch':{'activities':{'nature':3}}},ui=self.ui)
  self.assertEqual(a['turn']['skill'],'recommend');self.assertEqual(len(self.calls),1)
 def test_valid_map_origin_skips_redundant_city_question(self):
  a=self.send('see wild animals and walking with kids',{'action':'clarify','question':'Which city should we start from?','patch':{'activities':{'hiking':3,'nature':3},'needs':{'family_friendly':'preferred'}}},ui={'latitude':56.4,'longitude':-3.1,'minutes':120})
  self.assertEqual(a['turn']['skill'],'recommend');self.assertEqual(self.calls[0]['latitude'],56.4)
 def test_compound_nature_walk_repairs_model_omission(self):
  a=self.send('I would like a nature walk.',{'action':'recommend','patch':{'activities':{'nature':3}}},ui=self.ui)
  self.assertEqual(a['state']['activities'],{'nature':3,'hiking':3})
  self.assertEqual(self.calls[0]['activities'],a['state']['activities'])
  b=self.send('I am bringing children. Toilets would be useful.',{'action':'recommend','patch':{'activities':{'nature':3},'needs':{'family_friendly':'preferred','toilets':'preferred'}}},a['session_id'])
  self.assertIn('hiking',b['state']['activities']);self.assertIn('nature',b['state']['activities'])
 def test_explicit_activity_cancellation_is_respected(self):
  a=self.send('nature walk',{'action':'recommend','patch':{'activities':{'nature':3}}},ui=self.ui)
  b=self.send('No more hiking, only birdwatching.',{'action':'recommend','patch':{'activities':{'birdwatching':3}},'removed_activities':['hiking','nature']},a['session_id'])
  self.assertEqual(b['state']['activities'],{'birdwatching':3})
 def test_negated_nature_walk_is_not_added(self):
  for text in ["I don't want a nature walk, just cycling.",'Instead of a nature walk, I want cycling.','A nature walk is not needed.']:
   intent=d.normalize_activity_intent(text,{'action':'recommend','patch':{'activities':{'cycling':3}}},d.new_session()['state'])
   self.assertNotIn('hiking',intent['patch']['activities'])
 def test_explaining_compound_does_not_modify_preferences(self):
  intent=d.normalize_activity_intent('Why recommend a nature walk?',{'action':'explain','patch':{}},d.new_session()['state'])
  self.assertEqual(intent['patch'],{})
 def test_followups_preserve_and_cancel(self):
  first=self.send('观鸟散步',{'action':'recommend','patch':{'activities':{'birdwatching':3,'hiking':1}}},ui=self.ui)
  second=self.send('带孩子最好有厕所',{'action':'recommend','patch':{'needs':{'family_friendly':'preferred','toilets':'preferred'}}},first['session_id'])
  third=self.send('厕所必须有',{'action':'recommend','patch':{'needs':{'toilets':'required'}}},first['session_id'])
  self.assertEqual(third['state']['activities'],{'birdwatching':3,'hiking':1});self.assertEqual(third['state']['minutes'],60)
  fourth=self.send('不带孩子，厕所最好有',{'action':'recommend','patch':{'needs':{'family_friendly':'remove','toilets':'preferred'}}},first['session_id'])
  self.assertNotIn('family_friendly',fourth['state']['needs']);self.assertEqual(fourth['state']['needs']['toilets'],'preferred')
  loaded=d.handle({'command':'export','session_id':first['session_id']})
  self.assertEqual(len(loaded['turns']),4);self.assertIn('厕所必须有',loaded['markdown'])
 def test_clarification_and_answer(self):
  a=self.send('出去玩',{'action':'recommend','patch':{}},ui=self.ui)
  self.assertEqual(a['turn']['skill'],'clarify');self.assertEqual(len(self.calls),0)
  b=self.send('观鸟',{'action':'recommend','patch':{'activities':{'birdwatching':1}}},a['session_id'])
  self.assertEqual(len(self.calls),1);self.assertEqual(b['state']['city'],'Glasgow')
 def test_ambiguous_city_no_change(self):
  a=self.send('Edinburgh 呢',{'action':'clarify','question':'更换出发地还是目的地？','patch':{}},ui=self.ui)
  self.assertEqual(a['state']['city'],'Glasgow');self.assertFalse(self.calls)
 def test_session_isolation(self):
  a=self.send('观鸟',{'action':'recommend','patch':{'activities':{'birdwatching':1}}},ui=self.ui)
  b=self.send('散步',{'action':'recommend','patch':{'activities':{'hiking':1}}},ui={**self.ui,'city':'London'})
  self.assertNotEqual(a['session_id'],b['session_id']);self.assertEqual(d.read_session(a['session_id'])['state']['city'],'Glasgow')
 def test_unknown_and_closed_access(self):
  for value in (None,'','yes','destination','customers'):self.assertTrue(r.access_allowed(value))
  for value in ('no','private',' CLOSED '):self.assertFalse(r.access_allowed(value))
 def test_invalid_intent_does_not_mutate(self):
  a=self.send('错误',{'action':'recommend','patch':{'minutes':-2}},ui=self.ui)
  self.assertEqual(a['state']['minutes'],60);self.assertEqual(a['turn']['skill'],'service_error');self.assertFalse(self.calls)
 def test_hard_facility_needs_positive_quote(self):
  p={'name':'A','base_score':1,'maps_entity_match':{'status':'exact_or_subtype_name_match'},'maps_grounding':{'status':'ok','summary':'There are no toilets.'}}
  result={'recommendations':[p]}
  d.verify_facilities(result,{'toilets':'required'},lambda *a:{'places':[{'name':'A','needs':{'toilets':{'status':'no','quote':'There are no toilets.'}}}]})
  self.assertEqual(result['recommendations'],[])
  result={'recommendations':[copy.deepcopy(p)]}
  d.verify_facilities(result,{'toilets':'required'},lambda *a:{'places':[{'name':'A','needs':{'toilets':{'status':'yes','quote':'Invented toilets available.'}}}]})
  self.assertEqual(result['recommendations'],[])
 def test_disjoint_collinear_segments(self):
  self.assertFalse(w.segments_intersect((0,0),(1,0),(2,0),(3,0)))
  self.assertTrue(w.segments_intersect((0,0),(2,0),(1,0),(3,0)))
 def test_reset(self):
  a=self.send('观鸟',{'action':'recommend','patch':{'activities':{'birdwatching':1}}},ui=self.ui)
  b=self.send('重新开始',{'action':'reset'},a['session_id']);self.assertEqual(b['state']['activities'],{});self.assertTrue(b['clear_results'])
 def test_boundary_no_query(self):
  a=self.send('观鸟',{'action':'recommend','patch':{'activities':{'birdwatching':1}}},ui=self.ui)
  b=self.send('安静一点',{'action':'boundary','unsupported':['实时拥挤度']},a['session_id']);self.assertEqual(len(self.calls),1);self.assertIn('cannot reliably',b['turn']['assistant'])

if __name__=='__main__':unittest.main()
