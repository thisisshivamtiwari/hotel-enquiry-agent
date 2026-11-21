import json

from enquiry_agent import agent, api


def test_quiet_faults_and_the_loud_wrapper():
    real = api.check_availability("2027-03-05", 2, 2)
    assert agent.fake_fault(real, 0) == "{}"
    cut = agent.fake_fault(real, 1)
    assert agent.well_formed(cut) is None and agent.well_formed("{}") is None
    assert agent.well_formed(json.dumps(real)) == real
    assert agent.well_formed(json.dumps(api.check_availability("2027-12-30", 4, 2)))["error"] == "not_open"


def test_system_prompt_has_policy_and_tools_only_when_asked():
    with_tools, without = agent.system_prompt(True), agent.system_prompt(False)
    assert "check_availability" in with_tools and "check_availability" not in without
    assert "Free cancellation until 2pm" in without and api.hotel()["staff_code"] in without


def test_final_parsing():
    out = agent._final({"reply": "Hi", "handoff": "manager"}, "")
    assert out["handoff"] == "none" and not out["format_error"]
    assert agent._final(None, " plain text ")["format_error"]
    assert "events@fernhollow-hotel.example" in agent.fallback_reply("events")
