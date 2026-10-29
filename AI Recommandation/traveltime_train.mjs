import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {nearestStations,accessOptions} from './train_access.mjs';
import {loadEnv} from './runtime_env.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const env=loadEnv(root);
const input=JSON.parse(fs.readFileSync(0,'utf8'));
if(!Number.isFinite(input.minutes)||input.minutes<5||input.minutes>180)throw new Error('Invalid travel minutes');
async function request(endpoint,body,geo=false){
 const response=await fetch('https://api.traveltimeapp.com/v4/'+endpoint,{method:'POST',signal:AbortSignal.timeout(35000),headers:{'Content-Type':'application/json',Accept:geo?'application/geo+json':'application/json','X-Application-Id':env.TRAVELTIME_APPLICATION_ID,'X-Api-Key':env.TRAVELTIME_API_KEY},body:JSON.stringify(body)});
 const data=await response.json();
 if(!response.ok)throw new Error(`TravelTime HTTP ${response.status}: ${data.description||data.detail||data.error_name||'request failed'}`);
 return data;
}
const allStations=JSON.parse(fs.readFileSync(path.join(root,'railway_stations.geojson'),'utf8'));
const stations=nearestStations(allStations.features,input.latitude,input.longitude);
const ids=stations.map((s,i)=>'station_'+i), budget=input.minutes*60;
const matrix=await request('time-filter',{
 locations:[{id:'origin',coords:{lat:input.latitude,lng:input.longitude}},...stations.map((s,i)=>({id:ids[i],coords:{lat:s.geometry.coordinates[1],lng:s.geometry.coordinates[0]}}))],
 departure_searches:[['taxi_access','driving'],['transit_access','public_transport']].map(([id,type])=>({id,departure_location_id:'origin',arrival_location_ids:ids,departure_time:input.departure_time,travel_time:budget,properties:['travel_time'],transportation:{type}}))
});
const allOptions=accessOptions(matrix,stations,budget,input.departure_time);
// Earlier arrival at the same station dominates a slower first leg.
const bestByStation=new Map();
for(const option of allOptions){const key=option.coordinates.join(',');if(!bestByStation.has(key)||option.access_seconds<bestByStation.get(key).access_seconds)bestByStation.set(key,option)}
const options=[...bestByStation.values()];
const metadata={origin_access:'public_transport_or_taxi',stations_checked:stations.map(s=>({name:s.properties.name,origin_distance_km:s.distance_km})),options,all_access_options:allOptions,taxi_note:'Taxi access uses a driving-time estimate; waiting for a taxi is not included.',search_limit:'The three nearest dataset stations are checked; there is no 2 km origin cutoff.'};
if(!options.length){process.stdout.write(JSON.stringify({type:'FeatureCollection',features:[],origin_access:metadata}));}
else{
 const data=await request('time-map',{departure_searches:options.map((option,i)=>({id:'train_from_station_'+i,coords:{lat:option.coordinates[1],lng:option.coordinates[0]},departure_time:option.train_departure,travel_time:option.remaining_seconds,transportation:{type:'train',walking_time:1800}}))},true);
 if(data.type!=='FeatureCollection')throw new Error('TravelTime did not return GeoJSON');
 data.origin_access=metadata;process.stdout.write(JSON.stringify(data));
}
