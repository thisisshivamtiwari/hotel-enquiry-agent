"""The made-up hotel's booking system: one read-only lookup, `check_availability`, over the fixed tariff and the
rooms-left table in data/hotel.yaml. `python -m enquiry_agent api` serves it over HTTP on localhost; the experiment
calls the same function in-process.

A result lists every room type that fits the party (guests per room <= sleeps), whether it is free on every night,
the rate for each night, the total for all rooms, and a booking link for exactly that stay.
"""

import json
import math
from datetime import date, timedelta
from functools import cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

DATA = Path(__file__).resolve().parents[2] / "data"
MAX_ROOMS = 4  # 5 or more rooms is a group booking: the events team quotes it


@cache
def hotel() -> dict:
    return yaml.safe_load((DATA / "hotel.yaml").read_text())


def policy() -> str:
    return (DATA / "policy.md").read_text()


def season(d: date) -> str:
    return next(s for s, months in hotel()["seasons"].items() if d.month in months)


def rate(room: str, d: date) -> int:
    weekday, weekend = hotel()["rooms"][room]["rates"][season(d)]
    return weekend if d.weekday() in hotel()["weekend_nights"] else weekday


def rooms_left(room: str, d: date) -> int:
    return hotel()["rooms_left"].get(d.isoformat(), {}).get(room, hotel()["rooms"][room]["count"])


def book_url(check_in: str, nights: int, adults: int, children: int, rooms: int, room: str) -> str:
    return (
        f"{hotel()['booking_url']}stay?in={check_in}&nights={nights}&adults={adults}&children={children}"
        f"&rooms={rooms}&room={room}"
    )


def _error(code: str, message: str) -> dict:
    return {"error": code, "message": message}


def check_availability(check_in: str, nights: int, adults: int, children: int = 0, rooms: int = 1, room_type=None) -> dict:
    try:
        start = date.fromisoformat(str(check_in))
        nights, adults, children, rooms = int(nights), int(adults), int(children or 0), int(rooms or 1)
    except (TypeError, ValueError):
        return _error("bad_request", "check_in must be YYYY-MM-DD; nights, adults, children and rooms must be whole numbers")
    today, last = date.fromisoformat(hotel()["today"]), date.fromisoformat(hotel()["open_until"])
    if start < today:
        return _error("past_date", f"check_in {start} is before today ({today})")
    if not 1 <= nights <= 14:
        return _error("bad_request", "nights must be 1 to 14")
    if start + timedelta(days=nights - 1) > last:
        return _error("not_open", f"rates and rooms are only open for nights up to {last}; later dates can't be quoted yet")
    if rooms > MAX_ROOMS:
        return _error("group_booking", f"{rooms} rooms is a group booking: only the events team quotes 5 or more rooms")
    if adults < 1 or rooms < 1:
        return _error("bad_request", "at least 1 adult and 1 room")
    per_room = math.ceil((adults + children) / rooms)
    nights_list = [start + timedelta(days=i) for i in range(nights)]
    options = []
    for room, info in hotel()["rooms"].items():
        if room_type and room != room_type:
            continue
        if per_room > info["sleeps"]:
            continue
        nightly = [{"night": d.isoformat(), "rate": rate(room, d)} for d in nights_list]
        free = all(rooms_left(room, d) >= rooms for d in nights_list)
        option = {"room_type": room, "name": info["name"], "sleeps": info["sleeps"], "available": free}
        if free:
            option |= {
                "nightly_rate_per_room": nightly,
                "total_for_all_rooms": sum(n["rate"] for n in nightly) * rooms,
                "book_url": book_url(start.isoformat(), nights, adults, children, rooms, room),
            }
        else:
            option["sold_out_nights"] = [d.isoformat() for d in nights_list if rooms_left(room, d) < rooms]
        options.append(option)
    return {
        "check_in": start.isoformat(),
        "check_out": (start + timedelta(days=nights)).isoformat(),
        "nights": nights,
        "adults": adults,
        "children": children,
        "rooms": rooms,
        "options": options,
        "currency": "GBP",
        "note": "Rates are per room per night, room only. Breakfast and extras are on the policy page.",
    }


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/availability":
            self.send_error(404)
            return
        args = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = json.dumps(check_availability(**args)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8077) -> None:
    print(f"fake booking API on http://127.0.0.1:{port}/availability?check_in=2027-03-05&nights=2&adults=2")
    HTTPServer(("127.0.0.1", port), _Handler).serve_forever()
