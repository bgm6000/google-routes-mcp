#!/usr/bin/env python3
"""
Google Routes MCP Server — Cloud Run (HTTP/SSE transport)
Requires env vars: GOOGLE_ROUTES_API_KEY, MCP_AUTH_TOKEN
"""

import asyncio
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

import mcp.server.sse
import mcp.types as types
from mcp.server import Server

API_KEY = os.environ.get("GOOGLE_ROUTES_API_KEY", "")
AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.staticDuration,routes.distanceMeters,routes.travelAdvisory"

app = Server("google-routes")


# ---------------------------------------------------------------------------
# Helpers (identical to local server)
# ---------------------------------------------------------------------------

def _parse_seconds(duration_str: str) -> int:
    return int(duration_str.rstrip("s"))


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _fmt_distance(meters: int, units: str) -> str:
    if units == "METRIC":
        return f"{meters / 1000:.1f} km"
    return f"{meters / 1609.344:.1f} mi"


def _call_routes_api(origin: str, destination: str, departure_time: str | None,
                     travel_mode: str, units: str) -> dict:
    if not API_KEY:
        raise ValueError("GOOGLE_ROUTES_API_KEY is not set.")

    # Only DRIVE and TWO_WHEELER support traffic-aware routing
    traffic_modes = {"DRIVE", "TWO_WHEELER"}
    body: dict = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": travel_mode,
        "computeAlternativeRoutes": False,
        "languageCode": "en-US",
        "units": units,
    }
    if travel_mode in traffic_modes:
        body["routingPreference"] = "TRAFFIC_AWARE_OPTIMAL"

    if departure_time:
        dt = datetime.fromisoformat(departure_time)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        body["departureTime"] = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        ROUTES_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        raise RuntimeError(f"Routes API error {e.code}: {body_text}") from e


def _summarise_route(route: dict, origin: str, destination: str,
                     departure_time: str | None, units: str) -> str:
    duration_sec = _parse_seconds(route["duration"])
    static_sec = _parse_seconds(route["staticDuration"])
    delay_sec = duration_sec - static_sec
    distance = _fmt_distance(route["distanceMeters"], units)

    lines = [
        f"{origin}  →  {destination}",
        f"Distance:            {distance}",
        f"Drive time:          {_fmt_duration(duration_sec)}  (with traffic)",
        f"No-traffic baseline: {_fmt_duration(static_sec)}",
    ]

    if delay_sec > 60:
        lines.append(f"Traffic delay:       +{_fmt_duration(delay_sec)}")
    else:
        lines.append("Traffic delay:       none")

    if departure_time:
        dt = datetime.fromisoformat(departure_time)
        lines.append(f"Departure:           {dt.strftime('%a %b %-d, %-I:%M %p')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="compute_route",
            description=(
                "Compute a driving route with traffic-aware travel time using Google Routes API. "
                "Returns drive time (with and without traffic), distance, and delay. "
                "Provide a departure_time to get traffic estimates for a specific day/time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Origin address or place name"},
                    "destination": {"type": "string", "description": "Destination address or place name"},
                    "departure_time": {
                        "type": "string",
                        "description": "Departure time as ISO 8601 string (e.g. '2025-03-18T09:00:00-07:00'). Defaults to now.",
                    },
                    "travel_mode": {
                        "type": "string",
                        "enum": ["DRIVE", "TWO_WHEELER", "BICYCLE", "WALK", "TRANSIT"],
                        "description": "Mode of travel. Defaults to DRIVE.",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["IMPERIAL", "METRIC"],
                        "description": "Distance units. Defaults to IMPERIAL (miles).",
                    },
                },
                "required": ["origin", "destination"],
            },
        ),
        types.Tool(
            name="compare_departure_times",
            description=(
                "Compare drive times for the same route across multiple departure times. "
                "Identifies the fastest departure window to avoid traffic."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Origin address or place name"},
                    "destination": {"type": "string", "description": "Destination address or place name"},
                    "departure_times": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of ISO 8601 departure times to compare",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["IMPERIAL", "METRIC"],
                        "description": "Distance units. Defaults to IMPERIAL.",
                    },
                },
                "required": ["origin", "destination", "departure_times"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "compute_route":
        return await _handle_compute_route(arguments)
    if name == "compare_departure_times":
        return await _handle_compare(arguments)
    raise ValueError(f"Unknown tool: {name}")


async def _handle_compute_route(args: dict) -> list[types.TextContent]:
    origin = args["origin"]
    destination = args["destination"]
    departure_time = args.get("departure_time")
    travel_mode = args.get("travel_mode", "DRIVE")
    units = args.get("units", "IMPERIAL")

    try:
        data = await asyncio.to_thread(
            _call_routes_api, origin, destination, departure_time, travel_mode, units
        )
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]

    routes = data.get("routes", [])
    if not routes:
        return [types.TextContent(type="text", text="No routes found between those locations.")]

    text = _summarise_route(routes[0], origin, destination, departure_time, units)
    return [types.TextContent(type="text", text=text)]


async def _handle_compare(args: dict) -> list[types.TextContent]:
    origin = args["origin"]
    destination = args["destination"]
    departure_times: list[str] = args["departure_times"]
    units = args.get("units", "IMPERIAL")

    if not departure_times:
        return [types.TextContent(type="text", text="No departure times provided.")]

    async def fetch_one(dt: str):
        try:
            data = await asyncio.to_thread(
                _call_routes_api, origin, destination, dt, "DRIVE", units
            )
            routes = data.get("routes", [])
            if not routes:
                return dt, None, "No route found"
            return dt, routes[0], None
        except Exception as e:
            return dt, None, str(e)

    results = await asyncio.gather(*[fetch_one(dt) for dt in departure_times])

    lines = [f"Route: {origin}  →  {destination}", ""]
    best_sec = None
    best_label = None

    for dt, route, err in results:
        parsed = datetime.fromisoformat(dt)
        label = parsed.strftime("%a %b %-d, %-I:%M %p")
        if err or route is None:
            lines.append(f"  {label}: error — {err}")
            continue

        duration_sec = _parse_seconds(route["duration"])
        static_sec = _parse_seconds(route["staticDuration"])
        delay_sec = duration_sec - static_sec

        if best_sec is None or duration_sec < best_sec:
            best_sec = duration_sec
            best_label = label

        delay_str = f"  (+{_fmt_duration(delay_sec)} traffic)" if delay_sec > 60 else ""
        lines.append(f"  {label}: {_fmt_duration(duration_sec)}{delay_str}")

    if best_label:
        lines += ["", f"Best departure: {best_label}  ({_fmt_duration(best_sec)})"]

    return [types.TextContent(type="text", text="\n".join(lines))]


# ---------------------------------------------------------------------------
# Starlette app with auth middleware
# ---------------------------------------------------------------------------

sse = mcp.server.sse.SseServerTransport("/messages/")


async def handle_sse(request: Request) -> Response:
    # Verify bearer token if one is configured
    if AUTH_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {AUTH_TOKEN}":
            return Response("Unauthorized", status_code=401)

    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())

    return Response()


starlette_app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
        Route("/health", endpoint=lambda r: Response("ok")),
    ]
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)
