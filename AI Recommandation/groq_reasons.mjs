import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {loadEnv} from './runtime_env.mjs';
const root=path.dirname(fileURLToPath(import.meta.url));
const env=loadEnv(root);
const places = JSON.parse(fs.readFileSync(0, "utf8"));
const model = env.GROQ_MODEL || "qwen/qwen3.8-27b";
if (!Array.isArray(places)) throw new Error("Expected a JSON array of recommendation candidates.");
const evidence = places.map(p => ({name:p.name, activity_score:p.activity_score, access:p.access, distance_km:p.distance_km, maps_summary:String(p.maps_grounding?.summary || "").slice(0, 360) || null, maps_match:p.maps_entity_match?.status}));
function cleanJson(content) { return String(content).replace(/^```json\s*/i, "").replace(/\s*```$/, "").trim(); }
function parseOne(content, name) { const parsed=JSON.parse(cleanJson(content)); const item=parsed.recommendation || parsed; if(typeof item?.reason!=="string" || !item.reason.trim()) throw new Error("Response did not contain a valid reason."); return {name,reason:item.reason.trim()}; }
async function requestOne(place, useJsonMode) { const prompt=`Write one concise English recommendation reason for this UK green space, in no more than 28 words. Use only the provided fields. Use the Maps summary only when maps_match is exact_or_subtype_name_match, related_named_place or spatial_alias_match. Never invent facilities. Return exactly one valid JSON object with no Markdown or extra text: {"name":"${place.name}","reason":"English reason"}. Data: ${JSON.stringify(place)}`; const body={model,temperature:0.2,max_tokens:220,messages:[{role:"user",content:prompt}]}; if(useJsonMode) body.response_format={type:"json_object"}; const response=await fetch("https://api.groq.com/openai/v1/chat/completions", {method:"POST",headers:{"Content-Type":"application/json",Authorization:`Bearer ${env.GROQ_API_KEY}`},body:JSON.stringify(body)}); const data=await response.json().catch(()=>({})); if(!response.ok) throw new Error(data.error?.message || `HTTP ${response.status}`); const content=data.choices?.[0]?.message?.content || ""; if(!content) throw new Error(data.error?.message || "Model returned empty content."); return content; }
async function reasonFor(place) { try { return parseOne(await requestOne(place, true), place.name); } catch(firstFailure) { try { return parseOne(await requestOne(place, false), place.name); } catch(retryFailure) { throw new Error(`${place.name}: JSON mode: ${firstFailure.message}; plain retry: ${retryFailure.message}`); } } }
const settled=await Promise.allSettled(evidence.map(reasonFor)); const reasons=settled.filter(item=>item.status==="fulfilled").map(item=>item.value); if(!reasons.length) throw new Error(`Groq returned no valid reasons. ${settled.map(item=>item.reason?.message).filter(Boolean).join(" | ")}`); process.stdout.write(JSON.stringify(reasons));
