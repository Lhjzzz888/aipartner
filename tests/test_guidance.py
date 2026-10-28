from driving_school_rights.guidance import CaseFacts, build_negotiation_plan, quick_chat_reply, recommend_routes


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


def test_missing_evidence_reply_suggests_recovery_without_inventing_facts():
    answer = quick_chat_reply(_case(description="教练态度恶劣，我没留证据"))
    assert "付款记录" in answer
    assert "不补造材料" in answer
    assert "12328" in answer

