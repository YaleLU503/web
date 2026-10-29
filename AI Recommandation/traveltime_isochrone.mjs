import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const env = {};
for (const line of fs.readFileSync(path.join(root, ".env"), "utf8").split(/\r?\n/)) {
  if (!line.includes("=") || line.trimStart().startsWith("#")) continue;
  const [key, ...value] = line.split("="); env[key.trim()] = value.join("=").trim();
}
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const minutes = Math.max(5, Math.min(180, Number(input.minutes) || 60));
const transport = ["driving+ferry", "public_transport", "walking+ferry", "cycling+ferry"].includes(input.transport) ? input.transport : "driving+ferry";
const response = await fetch("https://api.traveltimeapp.com/v4/time-map/fast", {
  method: "POST",
  headers: { "Content-Type": "application/json", Accept: "application/geo+json", "X-Application-Id": env.TRAVELTIME_APPLICATION_ID, "X-Api-Key": env.TRAVELTIME_API_KEY },
  body: JSON.stringify({ arrival_searches: { one_to_many: [{ id: "reachable_area", coords: { lat: input.latitude, lng: input.longitude }, arrival_time_period: "weekday_morning", travel_time: minutes * 60, transportation: { type: transport } }] } }),
});
const data = await response.json().catch(() => ({}));
if (!response.ok) { console.error(data.detail || data.description || data.error_name || `HTTP ${response.status}`); process.exit(1); }
process.stdout.write(JSON.stringify(data));
