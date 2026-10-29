import json
import math
import unittest
from unittest.mock import patch
import station_filter as sf
import recommend_demo

class StationTests(unittest.TestCase):
    def tearDown(self):
        sf.station_near_boundary.cache_clear()

    def test_threshold_and_edge_not_centroid(self):
        geometry={'type':'Polygon','coordinates':[[[-1,50],[1,50],[1,52],[-1,52],[-1,50]]]}
        for km, expected in [(1.999,True),(2,True),(2.001,False)]:
            station={'type':'Feature','properties':{'id':1,'name':'Test'},'geometry':{'type':'Point','coordinates':[1+math.degrees(km/sf.EARTH_KM/math.cos(math.radians(51))),51]}}
            with patch.object(sf,'station_data',return_value={'features':[station]}):
                sf.station_near_boundary.cache_clear()
                self.assertEqual(sf.nearest_station(geometry) is not None,expected)

    def test_multipolygon_and_missing_geometry(self):
        geometry={'type':'MultiPolygon','coordinates':[[[[0,50],[.01,50],[.01,50.01],[0,50.01],[0,50]]],[[[1,51],[1.01,51],[1.01,51.01],[1,51.01],[1,51]]]]}
        station={'type':'Feature','properties':{'name':'Second polygon'},'geometry':{'type':'Point','coordinates':[1,51]}}
        with patch.object(sf,'station_data',return_value={'features':[station]}):
            self.assertEqual(sf.nearest_station(geometry)['boundary_distance_km'],0)
            self.assertIsNone(sf.nearest_station(None))

    def test_inside_measures_boundary_not_zero(self):
        geometry={'type':'Polygon','coordinates':[[[-1,50],[1,50],[1,52],[-1,52],[-1,50]]]}
        station={'type':'Feature','properties':{},'geometry':{'type':'Point','coordinates':[0,51]}}
        with patch.object(sf,'station_data',return_value={'features':[station]}):
            self.assertIsNone(sf.nearest_station(geometry))

    def test_real_station_points(self):
        features=sf.station_data()['features']
        self.assertEqual(len(features),3444)
        self.assertTrue(all(f['geometry']['type']=='Point' for f in features))

if __name__=='__main__':
    unittest.main()
