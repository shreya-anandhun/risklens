"""Geography for the risk globe: port coordinates with a short description,
sea-lane waypoints per consignment, and the chokepoints each route passes.

Place descriptions are general, well-known facts. Every *risk level* shown on
the globe is computed from the (dummy) consignment signals, never stated here.
"""
from __future__ import annotations

# name -> (lat, lng, country, description)
PORTS: dict[str, tuple[float, float, str, str]] = {
    "Chittagong": (22.33, 91.81, "Bangladesh", "Bangladesh's main seaport on the Bay of Bengal, handling most of the country's container trade."),
    "Felixstowe": (51.96, 1.35, "United Kingdom", "The UK's busiest container port, on the Suffolk coast."),
    "Mombasa": (-4.06, 39.67, "Kenya", "The largest port in East Africa and the sea gateway for Kenya, Uganda and Rwanda."),
    "Jebel Ali": (25.01, 55.06, "United Arab Emirates", "Dubai's deep-water port and the largest container port in the Middle East."),
    "Sohar": (24.50, 56.63, "Oman", "Industrial port on Oman's Batinah coast, just outside the Strait of Hormuz."),
    "Chennai": (13.10, 80.30, "India", "One of India's largest ports on the east coast, serving the Tamil Nadu manufacturing belt."),
    "Kaohsiung": (22.61, 120.28, "Taiwan", "Taiwan's largest port and a major hub for electronics exports."),
    "Los Angeles": (33.74, -118.27, "United States", "Together with Long Beach, the busiest container port complex in the United States."),
    "Callao": (-12.05, -77.15, "Peru", "Peru's main port next to Lima, handling most of the country's mineral exports."),
    "Rotterdam": (51.95, 4.14, "Netherlands", "Europe's largest port, at the mouth of the Rhine and Meuse."),
    "Hamburg": (53.54, 9.97, "Germany", "Germany's largest port, on the river Elbe about 100 km from the North Sea."),
    "Newark": (40.69, -74.15, "United States", "Port Newark–Elizabeth, the main container terminal of the Port of New York and New Jersey."),
    "Columbus": (39.96, -83.00, "United States", "Inland logistics hub in Ohio, within a day's drive of much of the US population."),
    "Monterrey": (25.69, -100.32, "Mexico", "The industrial capital of northern Mexico and a major nearshoring destination."),
    # Ports that appear in alternatives or the what-if defaults
    "Dar es Salaam": (-6.82, 39.29, "Tanzania", "Tanzania's main port and a gateway for landlocked East and Central Africa."),
    "Salalah": (16.94, 54.00, "Oman", "Deep-water transshipment port on Oman's Arabian Sea coast, outside the Gulf."),
    "Long Beach": (33.75, -118.19, "United States", "Second busiest US container port, next to Los Angeles."),
    "Oakland": (37.80, -122.30, "United States", "Main container port of Northern California on San Francisco Bay."),
    "Antwerp": (51.26, 4.40, "Belgium", "Europe's second largest port, on the river Scheldt."),
    "Philadelphia": (39.90, -75.14, "United States", "Delaware River port serving the US mid-Atlantic."),
    "Taipei": (25.08, 121.23, "Taiwan", "Taoyuan International Airport, Taiwan's main air cargo gateway."),
    "Frankfurt": (50.04, 8.56, "Germany", "Frankfurt Airport, one of Europe's largest air cargo hubs."),
    "Bremerhaven": (53.55, 8.58, "Germany", "Germany's second largest container port, on the North Sea coast."),
    "Dhaka": (23.84, 90.40, "Bangladesh", "Hazrat Shahjalal International Airport, Bangladesh's main air cargo gateway."),
    "Shenzhen": (22.50, 113.90, "China", "One of the world's busiest container ports, in the Pearl River Delta."),
    "Shanghai": (31.23, 121.47, "China", "The world's busiest container port by volume."),
    "Singapore": (1.26, 103.84, "Singapore", "A leading transshipment hub at the southern end of the Strait of Malacca."),
    "Colombo": (6.94, 79.84, "Sri Lanka", "South Asia's main transshipment port, close to the main east–west shipping lane."),
    "Karachi": (24.84, 66.98, "Pakistan", "Pakistan's largest port, on the Arabian Sea."),
    "Mumbai": (18.95, 72.95, "India", "Jawaharlal Nehru Port, India's busiest container port."),
    "Busan": (35.10, 129.04, "South Korea", "South Korea's largest port and a major Northeast Asian transshipment hub."),
    "Houston": (29.73, -95.27, "United States", "Major Gulf Coast port serving the US energy and chemicals industry."),
    "Santos": (-23.96, -46.30, "Brazil", "Latin America's busiest container port, serving São Paulo."),
    "Durban": (-29.87, 31.03, "South Africa", "Sub-Saharan Africa's busiest container port."),
    "Pune": (18.52, 73.86, "India", "Automotive and engineering manufacturing hub in western India."),
}

# Interior waypoints (lat, lng) along each consignment's lane.
LANES: dict[str, list[tuple[float, float]]] = {
    "CN-26-0911": [(18.5, 89.5), (12.0, 86.0), (5.6, 80.5), (8.5, 72.0), (12.0, 58.0), (12.4, 47.0), (12.6, 43.4),
                   (16.0, 41.2), (21.5, 38.2), (27.5, 34.0), (30.2, 32.55), (32.2, 31.8), (34.0, 25.0), (37.0, 11.5),
                   (36.0, -5.6), (38.5, -10.0), (43.5, -10.0), (48.5, -5.5), (50.2, -1.5), (51.3, 1.8)],
    "CN-26-0914": [(-2.0, 43.0), (2.5, 48.5), (8.0, 53.0), (14.0, 57.5), (19.0, 60.5), (23.2, 59.8), (25.6, 57.5),
                   (26.5, 56.3), (25.6, 55.3)],
    "CN-26-0917": [(23.6, 59.0), (20.0, 62.0), (14.0, 67.5), (9.0, 74.0), (6.2, 78.5), (6.0, 81.3), (9.0, 81.8), (11.5, 80.8)],
    "CN-26-0920": [(24.0, 123.5), (28.0, 132.0), (32.5, 145.0), (36.0, 160.0), (38.0, 175.0), (38.0, -170.0),
                   (37.0, -155.0), (35.5, -140.0), (34.0, -125.0)],
    "CN-26-0922": [(-8.0, -80.5), (-2.0, -82.0), (4.0, -80.5), (7.8, -79.6), (8.9, -79.6), (9.4, -79.9), (12.0, -77.5),
                   (17.5, -73.5), (22.0, -68.0), (29.0, -55.0), (37.0, -38.0), (43.0, -22.0), (47.5, -10.0), (49.8, -3.0),
                   (51.0, 1.6), (51.9, 3.4)],
    "CN-26-0925": [(53.9, 8.4), (53.8, 5.0), (52.3, 2.8), (50.9, 1.3), (50.1, -2.5), (49.4, -6.5), (48.0, -20.0),
                   (45.5, -35.0), (42.5, -50.0), (40.8, -64.0), (40.4, -73.4)],
    "CN-26-0928": [(38.25, -85.76), (36.17, -86.78), (35.15, -90.05), (32.78, -96.80), (30.27, -97.74), (29.42, -98.49), (27.51, -99.51)],
}

# Chokepoints and risk areas; `factor` names the consignment input that sets its level.
HOTSPOTS = [
    {"id": "bay_bengal", "name": "Bay of Bengal", "lat": 15.5, "lng": 88.0, "factor": "weather_risk_index",
     "about": "Cyclone-prone waters, most active around the monsoon transitions.", "lanes": ["CN-26-0911"]},
    {"id": "bab_el_mandeb", "name": "Bab-el-Mandeb", "lat": 12.6, "lng": 43.4, "factor": "geopolitical_risk_index",
     "about": "The narrow strait between Yemen and the Horn of Africa that links the Red Sea to the Gulf of Aden.", "lanes": ["CN-26-0911"]},
    {"id": "suez", "name": "Suez Canal", "lat": 30.4, "lng": 32.35, "factor": "port_congestion_index",
     "about": "The canal linking the Mediterranean to the Red Sea, the shortest sea route between Asia and Europe.", "lanes": ["CN-26-0911"]},
    {"id": "hormuz", "name": "Strait of Hormuz", "lat": 26.55, "lng": 56.35, "factor": "geopolitical_risk_index",
     "about": "The strait between the Persian Gulf and the Gulf of Oman, one of the world's most important oil chokepoints.", "lanes": ["CN-26-0914"]},
    {"id": "arabian_sea", "name": "Arabian Sea", "lat": 15.0, "lng": 63.0, "factor": "weather_risk_index",
     "about": "Open-water leg with heavy swell during the southwest monsoon.", "lanes": ["CN-26-0914", "CN-26-0917"]},
    {"id": "north_pacific", "name": "North Pacific crossing", "lat": 37.5, "lng": -178.0, "factor": "weather_risk_index",
     "about": "Long trans-Pacific leg exposed to autumn and winter storm tracks.", "lanes": ["CN-26-0920"]},
    {"id": "panama", "name": "Panama Canal", "lat": 9.1, "lng": -79.7, "factor": "port_congestion_index",
     "about": "Lock canal linking the Pacific and Atlantic. Transit slots tighten when lake water levels fall.", "lanes": ["CN-26-0922"]},
    {"id": "channel", "name": "English Channel", "lat": 50.4, "lng": -1.0, "factor": "port_congestion_index",
     "about": "One of the busiest shipping lanes in the world, with strict traffic separation.", "lanes": ["CN-26-0911", "CN-26-0922", "CN-26-0925"]},
    {"id": "north_atlantic", "name": "North Atlantic", "lat": 46.5, "lng": -30.0, "factor": "weather_risk_index",
     "about": "Transatlantic leg where autumn storms can add days to a crossing.", "lanes": ["CN-26-0925"]},
    {"id": "laredo", "name": "Laredo border crossing", "lat": 27.5, "lng": -99.5, "factor": "geopolitical_risk_index",
     "about": "The busiest land port for US–Mexico trade. Customs queues set the pace of road freight.", "lanes": ["CN-26-0928"]},
]


def place(name: str | None) -> dict | None:
    if not name or name not in PORTS:
        return None
    lat, lng, country, about = PORTS[name]
    return {"name": name, "lat": lat, "lng": lng, "country": country, "about": about}


def route(rec: dict) -> dict | None:
    """Map geometry for one consignment, or None if its ports are unknown."""
    o, d = place(rec.get("origin_port")), place(rec.get("destination_port"))
    if not o or not d:
        return None
    air = str(rec.get("mode", "")).lower() == "air"
    interior = [] if air else LANES.get(rec.get("consignment_id"), [])
    pts = [(o["lat"], o["lng"]), *interior, (d["lat"], d["lng"])]
    return {"origin": o, "destination": d, "points": [list(p) for p in pts], "air": air}


def geo_payload(results: list[dict]) -> dict:
    routes = {r["consignment_id"]: route(r) for r in results}
    ids = {cid for cid, g in routes.items() if g}
    hotspots = [{**h, "lanes": [c for c in h["lanes"] if c in ids]} for h in HOTSPOTS]
    return {"routes": {k: v for k, v in routes.items() if v}, "hotspots": [h for h in hotspots if h["lanes"]],
            "unmapped": sorted(cid for cid, g in routes.items() if not g)}
