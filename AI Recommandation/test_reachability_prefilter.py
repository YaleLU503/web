"""Check the spatial prefilter against the original intersection behavior."""
import random
import unittest
from recommendation_web_demo import reachability_relation,geometry_polygons,point_in_polygon,rings_intersect

def legacy_reachability_relation(green_geometry, travel_collection):
    for travel_feature in travel_collection.get("features", []):
        for green_polygon in geometry_polygons(green_geometry):
            for travel_polygon in geometry_polygons(travel_feature.get("geometry", travel_feature)):
                if not green_polygon or not travel_polygon:
                    continue
                if any(point_in_polygon(point, travel_polygon) for point in green_polygon[0]) or any(point_in_polygon(point, green_polygon) for point in travel_polygon[0]):
                    return "overlaps_reachable_area"
                if rings_intersect(green_polygon[0], travel_polygon[0]):
                    return "edge_contact"
    return "outside_reachable_area"


class ReachabilityTests(unittest.TestCase):
 def test_disjoint_contained_crossing_and_touching(self):
  def poly(x,y,w,h):return {'type':'Polygon','coordinates':[[[x,y],[x+w,y],[x+w,y+h],[x,y+h],[x,y]]]}
  examples=[(poly(0,0,1,1),poly(3,3,1,1)),(poly(0,0,4,4),poly(1,1,1,1)),(poly(0,1,4,1),poly(1,0,1,4)),(poly(0,0,1,1),poly(1,0,1,1))]
  rng=random.Random(22)
  examples += [(poly(rng.uniform(-4,4),rng.uniform(-4,4),rng.uniform(.1,2),rng.uniform(.1,2)),poly(rng.uniform(-4,4),rng.uniform(-4,4),rng.uniform(.1,2),rng.uniform(.1,2))) for _ in range(300)]
  for a,b in examples:
   travel={'features':[{'geometry':b}]}
   self.assertEqual(reachability_relation(a,travel),legacy_reachability_relation(a,travel))
 def test_holes_and_multipart(self):
  ring=lambda x,y,w:[[x,y],[x+w,y],[x+w,y+w],[x,y+w],[x,y]]
  green={'type':'Polygon','coordinates':[ring(0,0,10),ring(2,2,6)]}
  travel={'features':[{'geometry':{'type':'MultiPolygon','coordinates':[[ring(3,3,1)],[ring(20,20,1)]]}}]}
  self.assertEqual(reachability_relation(green,travel),legacy_reachability_relation(green,travel))
if __name__=='__main__':unittest.main()
