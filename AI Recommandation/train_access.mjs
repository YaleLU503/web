// Shared pure planning helpers: no origin distance cutoff.
export function nearestStations(features, latitude, longitude, count=3){
 const rad=x=>x*Math.PI/180;
 const distance=f=>{const [lon,lat]=f.geometry.coordinates;const a=Math.sin(rad(lat-latitude)/2)**2+Math.cos(rad(latitude))*Math.cos(rad(lat))*Math.sin(rad(lon-longitude)/2)**2;return 6371.0088*2*Math.asin(Math.min(1,Math.sqrt(a)))};
 return features.filter(f=>f.geometry?.type==='Point').map(f=>({...f,distance_km:distance(f)})).sort((a,b)=>a.distance_km-b.distance_km).slice(0,count);
}
export function accessOptions(matrix,stations,budget,departure){
 const options=[];
 for(const result of matrix.results||[]){
  for(const location of result.locations||[]){
   const index=Number(location.id.replace('station_',''));
   const station=stations[index];if(!station)continue;
   const seconds=Math.min(...(location.properties||[]).map(p=>p.travel_time).filter(v=>Number.isFinite(v)&&v>=0));
   if(!Number.isFinite(seconds)||budget-seconds<60)continue;
   options.push({station:station.properties.name,coordinates:station.geometry.coordinates,origin_distance_km:station.distance_km,access_mode:result.search_id==='taxi_access'?'taxi_estimate':'public_transport',access_seconds:Math.ceil(seconds),remaining_seconds:Math.floor(budget-seconds),train_departure:new Date(new Date(departure).getTime()+Math.ceil(seconds)*1000).toISOString()});
  }
 }
 return options;
}
