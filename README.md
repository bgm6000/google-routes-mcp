# Google Routes MCP Server
Publisher Note: All files in this Repo have been generated with Claude Code, including this readme. 

An MCP (Model Context Protocol) server that provides traffic-aware drive times using the Google Routes API v2. Deployed on Google Cloud Run.

## Tools

### `compute_route`
Compute a driving route with real-time traffic estimates for a specific day and time.

**Parameters:**
- `origin` — starting address or place name
- `destination` — ending address or place name
- `departure_time` — ISO 8601 datetime (e.g. `2025-03-18T09:00:00-07:00`). Defaults to now.
- `travel_mode` — `DRIVE`, `TWO_WHEELER`, `BICYCLE`, `WALK`, or `TRANSIT`. Defaults to `DRIVE`.
- `units` — `IMPERIAL` (miles) or `METRIC` (km). Defaults to `IMPERIAL`.

**Example output:**
```
San Francisco, CA  →  San Jose, CA
Distance:            50.0 mi
Drive time:          1h 19m  (with traffic)
No-traffic baseline: 56m
Traffic delay:       +23m
Departure:           Tue Mar 18, 9:00 AM
```

### `compare_departure_times`
Compare drive times across multiple departure windows to find the fastest option.

**Parameters:**
- `origin` — starting address or place name
- `destination` — ending address or place name
- `departure_times` — list of ISO 8601 datetimes to compare
- `units` — `IMPERIAL` or `METRIC`. Defaults to `IMPERIAL`.

**Example output:**
```
Route: San Francisco, CA  →  San Jose, CA

  Tue Mar 18, 7:00 AM: 58m
  Tue Mar 18, 8:00 AM: 1h 19m  (+23m traffic)
  Tue Mar 18, 9:00 AM: 1h 8m  (+12m traffic)

Best departure: Tue Mar 18, 7:00 AM  (58m)
```

## Deployment

Hosted on Google Cloud Run. Pushes to `main` automatically trigger a rebuild and redeploy via Cloud Build.

**Service URL:** `https://google-routes-mcp-272758916831.us-central1.run.app`

## Connecting to Claude

Add as a custom connector in Claude CoWork or Claude desktop:

- **URL:** `https://google-routes-mcp-272758916831.us-central1.run.app/sse`

## Notes

- Traffic-aware routing is only available for `DRIVE` and `TWO_WHEELER` modes
- `departure_time` must be a future date/time — the Routes API uses historical traffic patterns for the specified day and time of week
- The Google Routes API key is stored server-side and never exposed to clients
