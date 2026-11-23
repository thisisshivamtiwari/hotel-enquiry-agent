import json

from enquiry_agent import agent, api, checks, faults

ARGS = faults.ARGS


def state(result, args=ARGS):
    return agent.lookup_state(result if isinstance(result, str) else json.dumps(result), args)[0]


def test_verified_missing_failed():
    real = api.check_availability(**ARGS)
    assert state(real) == "verified"
    assert state(api.check_availability("2027-12-30", 4, 2), {"check_in": "2027-12-30", "nights": 4, "adults": 2}) == "verified"
    assert state(agent.lookup({"nights": 2, "adults": 2})) == "missing"
    assert state("{}") == "failed" and state("TimeoutError: no answer") == "failed"
    assert state({**real, "options": []}) == "failed"
    assert state(api.check_availability(**{**ARGS, "check_in": "2027-02-26"})) == "failed"
    assert state(api.check_availability(**{**ARGS, "adults": 1})) == "failed"


def test_lookup_without_party_is_a_bad_request_not_a_crash():
    assert agent.lookup({"check_in": "2027-03-05"}) == {"error": "bad_request", "message": "nights and adults required"}


def test_sold_out_claim_needs_a_sold_out_answer():
    feb = [api.check_availability("2027-02-13", 2, 2)]
    assert "availability" in {p["rule"] for p in checks.check("Sorry, we have no rooms free.", [], "x")}
    assert "availability" not in {p["rule"] for p in checks.check("The Classic Double is sold out.", feb, "x")}
    assert checks.check("Our booking system is unavailable just now; reservations will confirm.", [], "x") == []


def test_every_fixture_case_is_handled_and_results_reproduce():
    res = faults.run()
    assert res["passed"] == res["cases"]
    assert res == json.loads(faults.OUT.read_text())
