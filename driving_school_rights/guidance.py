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
        RouteRecommendation("12328", "驾校备案、培训管理、教练教学或培训记录等交通运输行业问题", ("合同", "付款凭证", "培训记录", "沟通证据"), ("先书面向驾校提出具体诉求", "仍无法解决时向12328反映并保留工单编号"), "主要处理交通运输行业监管与服务事项，不直接裁决合同退款金额。"),
        RouteRecommendation("12315", "经营者服务或消费权益争议；消费纠纷可投诉，涉嫌违法线索可另行举报", ("经营者名称", "合同", "付款与履约证据", "明确诉求"), ("通过12315平台选择投诉或举报类型", "提交证据并留存编号"), "调解不等于行政裁决，也不保证退款；投诉与举报的目的不同。"),
        RouteRecommendation("12345", "不清楚属于哪个属地部门，或希望反映政务服务、请求转办", ("所在市县", "事件摘要", "希望承办的事项"), ("拨打12345或使用当地政务平台", "说明已联系的部门及现有工单号"), "转办和处理时限依当地规则，不能替代司法程序。"),
        RouteRecommendation("12348", "需要法律咨询、公共法律服务或了解法律援助申请入口", ("合同", "时间线", "金额与证据清单"), ("咨询法律关系及下一步程序", "如考虑法律援助，向当地机构核实事项和资格"), "法律援助有法定事项和经济条件等要求，热线咨询不等于已获援助。"),
        RouteRecommendation("12368", "已考虑诉讼，需查询法院诉讼服务和程序性问题", ("对方主体信息", "合同及证据", "请求和金额"), ("先核对有管辖权的法院与起诉条件", "通过法院官方渠道提交或查询"), "主要是法院诉讼服务，不作一般合同争议的实体法律判断。"),
        RouteRecommendation("110", "仅在正在发生的人身安全危险、暴力威胁等紧急情况", ("当前位置", "危险情况", "可识别涉事人员信息"), ("先离开危险环境并报警", "保存安全可行的证据"), "一般退款、服务或态度争议不属于紧急报警事项。"),
    ]


def build_negotiation_plan(case: CaseFacts) -> NegotiationPlan:
    evidence = ("培訓合同及補充約定", "付款憑證與收據", "已完成及未完成課時記錄", "預約、取消及溝通截圖", "按日期整理的事件時間線")
    if case.urgent_safety_risk:
        return NegotiationPlan("先保障人身安全，离开危险场所并视情况联系110。", "暂缓协商，先处理安全与证据保存。", "安全后再以书面方式联系驾校负责人。", evidence, ("人身安全", "保存证据", "安全后书面沟通", "按问题选择主管渠道"), None)
    first = "先核对合同、付款、已学课时和退费计算依据，再形成书面诉求。" if case.confirmed_amount is None else "整理合同、付款和履约证据，向驾校提交书面诉求并要求书面答复。"
    amount = case.confirmed_amount
    return NegotiationPlan(first, "要求驾校按合同及实际履行情况提出退费或补救方案" + (f"，暂列金额 {amount:g} 元" if amount is not None else "，金额待核对"), "如不能一次解决，可提出分期退费、转校/转教练或补足课时等可核实的备选方案。", evidence, ("核对合同和金额", "向驾校负责人书面协商", "保留送达和回复记录", "必要时依次使用12328、12315或12345等渠道", "评估调解、仲裁条款或诉讼"), amount)
