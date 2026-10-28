from driving_school_rights.guidance import CaseFacts, build_negotiation_plan, recommend_routes


def _case(**changes):
    values = dict(issue_type="退款", city="济南", description="课程未完成，想退费", confirmed_amount=None, urgent_safety_risk=False)
    values.update(changes)
    return CaseFacts(**values)


def test_routes_distinguish_12328_12315_12345_12348_12368_110():
    routes = recommend_routes(_case(urgent_safety_risk=True))
    names = {route.channel for route in routes}
    assert {"12328", "12315", "12345", "12348", "12368", "110"} <= names
    emergency = next(route for route in routes if route.channel == "110")
    assert "紧急" in emergency.when_to_use


def test_negotiation_plan_uses_confirmed_amounts_only():
    plan = build_negotiation_plan(_case(confirmed_amount=None))
    assert plan.request_amount is None
    assert "核对" in plan.first_step


def test_urgent_safety_skips_ordinary_negotiation():
    plan = build_negotiation_plan(_case(urgent_safety_risk=True))
    assert plan.first_step.startswith("先保障人身安全")
