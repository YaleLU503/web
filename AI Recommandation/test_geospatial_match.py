# -*- coding: utf-8 -*-
import json,unittest
from pathlib import Path
from geospatial_match import spatial_alias
from recommend_demo import maps_entity_match
from visitor_reviews import component_scope

class SpatialAliasTests(unittest.TestCase):
 def setUp(self):
  self.geometry={'type':'Polygon','coordinates':[[[0,50],[.01,50],[.01,50.01],[0,50.01],[0,50]]]}
  self.candidate={'name':'Bushy Park and Home Park','_geometry':self.geometry}
  self.place={'id':'test','attribution':{'title':'Bushy Park - Google Maps'},'location':{'latitude':50.005,'longitude':.005}}
 def test_component_name_inside_is_accepted(self):
  self.assertEqual(spatial_alias(self.candidate,self.place)['status'],'spatial_alias_match')
  self.assertEqual(component_scope(self.candidate,self.place)[0],'geographic_alias')
 def test_near_boundary_is_accepted(self):
  self.place['location']['longitude']=.012
  self.assertEqual(spatial_alias(self.candidate,self.place)['spatial_relation'],'near_green_space_boundary')
 def test_same_name_far_away_is_rejected(self):
  self.place['location']['longitude']=10
  self.assertIsNone(spatial_alias(self.candidate,self.place))
  self.assertEqual(maps_entity_match(self.candidate['name'],[self.place],self.geometry)['status'],'spatial_mismatch')
 def test_facility_poi_not_treated_as_green_space(self):
  self.place['attribution']['title']='Bushy Park Car Park - Google Maps'
  self.assertIsNone(spatial_alias(self.candidate,self.place))
 def test_unrelated_nearby_name_is_rejected(self):
  self.place['attribution']['title']='Richmond Park - Google Maps'
  self.assertIsNone(spatial_alias(self.candidate,self.place))
 def test_real_bushy_record(self):
  root=Path(__file__).resolve().parent
  data=json.loads((root/'natural_assets_2.geojson').read_text(encoding='utf-8'))
  feature=next(f for f in data['features'] if 'Bushy Park and Home Park' in f['properties'].values())
  candidate={'name':'Bushy Park and Home Park','_geometry':feature['geometry']}
  place={'attribution':{'title':'Bushy Park - Google Maps'},'location':{'latitude':51.416531,'longitude':-0.3398173}}
  match=spatial_alias(candidate,place)
  self.assertIsNotNone(match);self.assertEqual(match['status'],'spatial_alias_match')
  print('Real Bushy Park match:',match['spatial_relation'])

if __name__=='__main__':unittest.main()
