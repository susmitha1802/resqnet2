# Local map data and Hyderabad sample

The exact message "Severe flash flooding expected in the Hyderabad region over
the next 48 hours." comes from `backend/seed_demo.py`. The legacy record claims
OpenWeatherMap as its source but is an authored scenario, not a weather API
response. Its location is 17.4401, 78.4487 and its radius is 50 km. The current
original SQLite alert matched this seed exactly. Normal empty-database startup
does not seed; demo seeding requires an explicit development-only opt-in.

`GET /map/risk-zones` reads persisted WeatherAlert records; it does not fetch
weather. Its High/Medium/Low values are rule-based estimates from the stored
severity, text, and nearby reports, not independently verified predictions.
Actual weather pulls happen separately through `/weather/live` and the admin
`POST /alerts/fetch` workflow. Manually entered alerts retain source Manual.

Demo alerts, SOS requests and incident reports are now excluded from default
`/map/data`, `/map/risk-zones`, and `/alerts` responses. Exact legacy seed
fingerprints remain recognized without changing records or adding columns.
New seed alerts explicitly identify their source; new seed incidents carry a
persisted `[DEMO]` description. Real records are not classified by city alone.
An explicit `?include_demo=1` API preview returns demo metadata and warning
labels. Default live maps defensively omit demo risk zones and incidents,
including the exact legacy alert returned by an older backend. Demo alerts
cannot initiate live preparedness notifications.

The full map now defaults to an India overview. Valid `lat`/`lng` links,
including zero coordinates, override that initial view. Request/report links
focus their target once. Polling and filter changes retain the user's viewport;
address search and existing manual controls still navigate explicitly.
Popup locations/status/source come from each record. Reports are labelled
unverified because their model has no independently verified incident status.
Flood Intelligence layers and scientific warnings are unchanged.

The forms' existing Detect Location fix remains in place: browser GPS is
requested on click, coordinates are usable before optional Nominatim reverse
lookup, and denial/timeout/lookup failure preserves manual selection. No
documentation URL is used as an API endpoint.

For local backend changes, ensure the browser uses the local API override
documented in LOCAL_FLOOD.md. Localhost pages default to the local backend;
hosted pages retain their previous configured hosted default.

Focused checks from `resqnet1` (existing environments only):

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s backend\tests -p test_map_provenance.py -v
node --test frontend\tests\map-display.test.cjs frontend\tests\detect-location.test.cjs
node frontend\tests\detect-location.browser.cjs
```

Backend checks use an isolated memory database. Browser checks use installed
Chrome, simulated GPS and mocked incidents/geocoding/tiles; no actual warnings,
SOS submissions, or real tile downloads are generated.
