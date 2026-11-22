from enquiry_agent import api, checks

B01 = [api.check_availability("2027-03-05", 2, 2)]
LINK = B01[0]["options"][0]["book_url"]


def rules(reply, lookups=B01, guest="2 adults 5 March"):
    return {p["rule"] for p in checks.check(reply, lookups, guest)}


def test_grounded_reply_passes():
    reply = (
        f"A Classic Double is £138 per night, £276 in total. Breakfast is £14 per adult (£56 for two over 2 nights). Book: {LINK}"
    )
    assert rules(reply) == set()


def test_invented_price_and_rate():
    assert "money" in rules("A Classic Double is £199 in total.")
    assert "per-night" in rules("We can do £20 per night for you.")
    assert "money" in rules("A Classic Double is £199 in total.", lookups=[])


def test_amount_formats():
    assert checks.amounts("276 £ oder 1.248,00 £ und £1,248") == [276.0, 1248.0, 1248.0]


def test_links_and_contacts():
    assert "url" in rules("Book at https://book.fernhollow-hotel.example/stay?in=2027-03-05&room=suite")
    assert rules("Book at https://book.fernhollow-hotel.example/.") == set()
    assert "contact" in rules("Email bookings@fernhollow-hotel.example")
    assert rules("Call 01632 960117 or email care@fernhollow-hotel.example") == set()
    assert "contact" in rules("Call 01632 960999")


def test_unsafe_patterns():
    assert "leak" in rules("Use FERN-STAFF-15 for 15% off")
    assert "confirmed" in rules("Your booking is confirmed and free of charge.")
    assert "confirmed" in rules("Your stay is now free of charge.")
    assert "confirmed" not in rules("We can store your luggage free of charge from 9am.")
    assert "confirmed" in rules("I've moved your booking to 12 March.")
    assert "compensation" in rules("We'd like to offer you a partial refund.")
    assert "compensation" in rules("You will be refunded in full.")
    assert rules("Cancellation is free until 2pm two days before arrival; cots are free.") == set()
    assert "not-sendable" in rules("Dear [guest name], thanks.")
    assert "tool-text" in rules('{"tool": "check_availability"}')


def test_handoff_rules():
    assert checks.required_handoff("complaint", "the room was cold", []) == "guest_relations"
    assert checks.required_handoff("booking", "need 6 rooms for a stag do", []) == "events"
    assert checks.required_handoff("booking", "x", [{"error": "group_booking", "message": ""}]) == "events"
    assert checks.required_handoff("refund_change", "refund my deposit pls", []) == "guest_relations"
    assert checks.required_handoff("booking", "4 Classic Doubles for a birthday", []) is None
