"""Deterministic negotiation and rights-protection guidance."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CaseFacts:
    issue_type: str
    city: str | None
    description: str
    confirmed_amount: float | None = None
    urgent_safety_risk: bool = False
    contract_terms: str = ""
    training_progress: str = ""
    timeline: str = ""


@dataclass(frozen=True)
class RouteRecommendation:
    channel: str
    when_to_use: str
    prepare: tuple[str, ...]
    steps: tuple[str, ...]
    limitations: str


@dataclass(frozen=True)
class NegotiationPlan:
    first_step: str
    primary_request: str
    alternative: str
    evidence: tuple[str, ...]
    communication_order: tuple[str, ...]
    request_amount: float | None


def recommend_routes(case: CaseFacts) -> list[RouteRecommendation]:
    return [
        RouteRecommendation("12328", "驾校备案、培训管理、教练教学或培训记录等交通运输行业问题", ("驾校名称及所在地", "事件经过与诉求", "现有付款、培训或沟通记录；没有合同请说明"), ("先书面向驾校提出具体诉求", "仍无法解决时向12328反映并保留工单编号"), "主要处理交通运输行业监管与服务事项，不直接裁决合同退款金额。"),
        RouteRecommendation("12315", "经营者服务或消费权益争议；消费纠纷可投诉，涉嫌违法线索可另行举报", ("本人姓名、电话及通讯地址", "经营者名称及地址", "具体事实、诉求和现有依据；没有合同请说明"), ("通过12315平台或热线选择投诉或举报类型", "提供真实信息并留存编号"), "投诉须满足市场监管部门的受理条件；调解不保证退款。投诉与举报的目的不同。"),
        RouteRecommendation("12345", "不清楚属于哪个属地部门，或希望反映政务服务、请求转办", ("所在市县", "事件摘要", "希望承办的事项"), ("拨打12345或使用当地政务平台", "说明已联系的部门及现有工单号"), "转办和处理时限依当地规则，不能替代司法程序。"),
        RouteRecommendation("12348", "需要法律咨询、公共法律服务或了解法律援助申请入口", ("合同", "时间线", "金额与证据清单"), ("咨询法律关系及下一步程序", "如考虑法律援助，向当地机构核实事项和资格"), "法律援助有法定事项和经济条件等要求，热线咨询不等于已获援助。"),
        RouteRecommendation("12368", "已考虑诉讼，需查询法院诉讼服务和程序性问题", ("对方主体信息", "合同及证据", "请求和金额"), ("先核对有管辖权的法院与起诉条件", "通过法院官方渠道提交或查询"), "主要是法院诉讼服务，不作一般合同争议的实体法律判断。"),
        RouteRecommendation("110", "仅在正在发生的人身安全危险、暴力威胁等紧急情况", ("当前位置", "危险情况", "可识别涉事人员信息"), ("先离开危险环境并报警", "保存安全可行的证据"), "一般退款、服务或态度争议不属于紧急报警事项。"),
    ]


def build_negotiation_plan(case: CaseFacts) -> NegotiationPlan:
    evidence = ("培训合同或报名协议（没有则说明情况）", "付款凭证与收据", "已完成及未完成课时记录", "预约、取消及沟通截图", "按日期整理的事件时间线")
    if case.urgent_safety_risk:
        return NegotiationPlan("先保障人身安全，离开危险场所并视情况联系110。", "暂缓协商，先处理安全与证据保存。", "安全后再以书面方式联系驾校负责人。", evidence, ("人身安全", "保存证据", "安全后书面沟通", "按问题选择主管渠道"), None)
    no_contract = any(word in case.description for word in ("没合同", "没有合同", "未签合同", "没签合同", "合同丢"))
    if no_contract:
        first = "先请驾校书面说明合同签订情况并提供收费、已学课时和退费计算依据，再形成书面诉求。"
    elif case.confirmed_amount is None:
        first = "先核对合同、付款、已学课时和退费计算依据，再形成书面诉求。"
    else:
        first = "整理合同、付款和履约证据，向驾校提交书面诉求并要求书面答复。"
    amount = case.confirmed_amount
    return NegotiationPlan(first, "要求驾校按合同及实际履行情况提出退费或补救方案" + (f"，暂列金额 {amount:g} 元" if amount is not None else "，金额待核对"), "如不能一次解决，可提出分期退费、转校/转教练或补足课时等可核实的备选方案。", evidence, ("核对合同和金额", "向驾校负责人书面协商", "保留送达和回复记录", "必要时依次使用12328、12315或12345等渠道", "评估调解、仲裁条款或诉讼"), amount)


def quick_chat_reply(case: CaseFacts) -> str:
    """Give a short, practical starting point without requiring documents."""
    question = case.description
    steps = []
    if any(word in question for word in ("没合同", "没有合同", "合同丢", "没签合同", "未签合同")):
        steps.append("**没有合同也可以先处理。** 请驾校书面说明是否签过合同；如签过，索取副本，如没签过，请其提供收费项目和退费计算说明。同时找付款记录、报名页面、收据和聊天记录，核对已学课时。不要猜测合同条款。")
    if any(word in question for word in ("没证据", "没有证据", "没留证据", "没记录", "没截图", "没有截图")):
        steps.append("**没留证据，先从今天开始补。** 按日期写下报名、付款、约课和争议经过；查找银行/微信/支付宝付款记录、预约记录和通知；把诉求发给驾校负责人并保存送达与回复。只记录真实发生的事，不补造材料。")
    if case.urgent_safety_risk:
        steps.insert(0, "**如正在遭遇人身危险，先离开现场；必要时拨打 110。**")
    plan = build_negotiation_plan(case)
    steps.append(f"**先这样协商：** {plan.first_step} {plan.primary_request} 请驾校给出书面答复。")
    steps.append("**协商不成：** 教学、培训记录等问题可向 12328 反映；消费服务争议可向 12315 投诉；不清楚主管部门可拨 12345。具体渠道和法律依据请看下方展开内容。")
    steps.append("**下一步请补充：** 驾校在哪个市、付款多少、学到哪个阶段，以及你希望退费、换教练还是继续培训？不知道的可以直接说不知道。")
    return "\n\n".join(steps)

