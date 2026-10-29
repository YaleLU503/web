# -*- coding: utf-8 -*-
"""Recognize map aliases using distinctive names and the actual green-space polygon."""
import difflib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from station_filter import vector,segment_distance

ALIAS_BOUNDARY_KM=.5
GENERIC={'park','country','national','forest','woods','wood','nature','reserve','green','space','and','the','of','google','maps'}
POI=re.compile(r'\b(?:restaurant|cafe|café|hotel|pub|station|toilets?|restrooms?|parking|car park|entrance|visitor cent(?:re|er)|playground)\b',re.I)

@lru_cache(maxsize=1)
def geometries():
    features=json.loads(Path(__file__).with_name('natural_assets_2.geojson').read_text(encoding='utf-8'))['features']
    return features


def geometry_for(candidate):
    if candidate.get('_geometry'):return candidate['_geometry']
    matches=[f for f in geometries() if candidate.get('place_id') is not None and str(f.get('properties',{}).get('fid'))==str(candidate['place_id'])]
    if not matches:matches=[f for f in geometries() if f.get('properties',{}).get('name')==candidate.get('name')]
    return matches[0].get('geometry') if len(matches)==1 else None


def in_ring(point,ring):
    x,y=point;inside=False
    for i,a in enumerate(ring):
        b=ring[i-1]
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:inside=not inside
    return inside


def spatial_alias(candidate,place,geometry=None):
    title=place.get('attribution',{}).get('title','').split(' - Google Maps')[0].strip()
    if POI.search(title):return None
    def tokens(name):return set(re.findall(r'[a-z]+',name.lower()))-GENERIC
    query,source=tokens(candidate.get('name','')),tokens(title)
    overlap=query&source
    spelling=any(difflib.SequenceMatcher(None,a,b).ratio()>=.86 for a in query for b in source)
    if not overlap and not spelling:return None
    location=place.get('location',{})
    lat,lon=location.get('latitude'),location.get('longitude')
    if not all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) for v in (lat,lon)):return None
    geometry=geometry or geometry_for(candidate)
    if not geometry:return None
    polygons=[geometry['coordinates']] if geometry.get('type')=='Polygon' else geometry.get('coordinates',[]) if geometry.get('type')=='MultiPolygon' else []
    for polygon in polygons:
        if polygon and in_ring((lon,lat),polygon[0]) and not any(in_ring((lon,lat),hole) for hole in polygon[1:]):
            return {'status':'spatial_alias_match','source_title':title,'spatial_relation':'inside_green_space','boundary_distance_km':None,'distance_to_green_space_km':0,'source_place_id':place.get('id'),'note':'Related name and Google point inside the dataset green-space geometry.'}
    p=vector((lon,lat));minimum=math.inf
    for polygon in polygons:
        for ring in polygon:
            for i,a in enumerate(ring):minimum=min(minimum,segment_distance(p,vector(a),vector(ring[(i+1)%len(ring)])))
    if minimum<=ALIAS_BOUNDARY_KM:
        return {'status':'spatial_alias_match','source_title':title,'spatial_relation':'near_green_space_boundary','boundary_distance_km':minimum,'source_place_id':place.get('id'),'note':'Related name and Google point within 500 m of the dataset boundary.'}
    return None
