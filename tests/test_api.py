from enquiry_agent import api


def test_weekend_and_season_rates():
    r = api.check_availability("2027-03-05", 2, 2, room_type="classic")
    assert r["options"][0]["nightly_rate_per_room"] == [
        {"night": "2027-03-05", "rate": 138},
        {"night": "2027-03-06", "rate": 138},
    ]
    assert r["options"][0]["total_for_all_rooms"] == 276
    assert api.rate("classic", api.date(2027, 8, 2)) == 149  # high season Monday


def test_sold_out_night_blocks_the_stay():
    r = api.check_availability("2027-02-13", 2, 2)
    free = {o["room_type"]: o["available"] for o in r["options"]}
    assert free == {"classic": False, "garden": False, "family": True, "accessible": True}
    assert r["options"][0]["sold_out_nights"] == ["2027-02-13"]


def test_party_size_filters_rooms_and_multiplies_totals():
    assert [o["room_type"] for o in api.check_availability("2027-06-10", 2, 3)["options"]] == ["family"]
    two = api.check_availability("2027-07-16", 2, 4, rooms=2, room_type="classic")["options"][0]
    assert two["total_for_all_rooms"] == 2 * (182 + 182)
    assert "rooms=2" in two["book_url"]


def test_errors():
    assert api.check_availability("2027-01-20", 1, 2)["error"] == "past_date"
    assert api.check_availability("2027-12-30", 4, 2)["error"] == "not_open"
    assert api.check_availability("2027-03-12", 2, 12, rooms=6)["error"] == "group_booking"
    assert api.check_availability("12 March", 2, 2)["error"] == "bad_request"
