# -*- coding: utf-8 -*-
import copy
import unittest
import io
import json
from unittest.mock import patch
from recommendation_fit import explain_fit,google_context
from visitor_reviews import component_scope,extract_excerpts,fetch_reviews

class EvidenceTests(unittest.TestCase):
 def setUp(self):
  self.place={'id':'test','attribution':{'title':'Bushy Park - Google Maps','url':'https://www.google.com/maps/place/test'},'googleMapsLinks':{'reviewsUrl':'https://www.google.com/maps/place/test/reviews'}}
  self.candidate={'name':'Bushy Park and Home Park','activity_score_breakdown':{'nature':{'raw_score':.68},'hiking':{'raw_score':.34}},'maps_entity_match':{'status':'weak_name_match'},'maps_grounding':{'status':'ok','summary':'Visitors mention family-friendly walks. Toilets are available.','places':[self.place]},'facility_evidence':{'toilets':{'status':'unknown','quote':''}},'nearest_station':{'name':'Hampton Wick','boundary_distance_km':.27}}
 def test_requirements_explained_individually(self):
  answer=explain_fit(self.candidate,{'toilets':'preferred'})
  self.assertIn('wish to walk',answer);self.assertIn('ecological',answer);self.assertIn('Not verified',answer)
 def test_component_source_never_confirms_entire_area(self):
  self.assertEqual(component_scope(self.candidate,self.place)[0],'component_only')
  self.assertIn('cannot verify the whole',explain_fit(self.candidate))
 def test_unrelated_place_is_not_used(self):
  bad=copy.deepcopy(self.place);bad['attribution']['title']='Another Park - Google Maps'
  self.candidate['maps_grounding']['places']=[bad]
  self.assertIsNone(google_context(self.candidate))
 def test_review_preserves_negative_feedback_and_attribution(self):
  review={'text':{'text':'No toilets near the walking paths.'},'authorAttribution':{'displayName':'A visitor','uri':'https://example.com/profile'},'publishTime':'2026-01-01T12:00:00Z','googleMapsUri':'https://example.com/review'}
  excerpt=extract_excerpts([review],['toilets','hiking'])[0]
  self.assertTrue(excerpt['quote'].startswith('No toilets'));self.assertEqual(excerpt['author'],'A visitor');self.assertEqual(excerpt['review_url'],'https://example.com/review')
 def test_absent_reviews_not_presented_as_feedback(self):
  self.candidate['visitor_reviews']={'status':'ok','returned_count':0,'excerpts':[]}
  self.assertIn('no individual review text',explain_fit(self.candidate))

 def test_review_summary_without_individual_reviews(self):
  summary={'text':{'text':'Visitors enjoy the walks but mention crowds.'},'disclosureText':{'text':'Summarized with Gemini'},'reviewsUri':'https://example.com/reviews','flagContentUri':'https://example.com/report'}
  response={'id':'test','displayName':{'text':'Bushy Park'},'reviewSummary':summary}
  with patch('visitor_reviews.rec.read_env_value',return_value='test-key'),patch('visitor_reviews.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as request:
   reviews=fetch_reviews(self.candidate,['hiking'])
  self.assertIn('reviewSummary',request.call_args.args[0].get_header('X-goog-fieldmask'))
  self.assertEqual(reviews['review_summary'],summary)
  self.assertTrue(reviews['review_summary_requested'])
  self.assertEqual(reviews['returned_count'],0)
  self.candidate['visitor_reviews']=reviews
  answer=explain_fit(self.candidate)
  for value in [summary['text']['text'],'Summarized with Gemini',summary['reviewsUri'],summary['flagContentUri']]:self.assertIn(value,answer)

 def test_missing_summary_not_replaced_with_place_summary(self):
  self.candidate['visitor_reviews']={'status':'ok','returned_count':0,'excerpts':[],'review_summary':{}}
  self.assertIn('No review consensus has been inferred',explain_fit(self.candidate))

 def test_summary_without_attribution_not_displayed(self):
  self.candidate['visitor_reviews']={'status':'ok','review_summary':{'text':{'text':'UNATTRIBUTED SUMMARY'}},'returned_count':0}
  self.assertNotIn('UNATTRIBUTED SUMMARY',explain_fit(self.candidate))

if __name__=='__main__':unittest.main()
