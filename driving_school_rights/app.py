"""Standalone Shandong driving-school rights assistant Streamlit app."""

from datetime import date
import hashlib
import json
import logging

import streamlit as st

from driving_school_rights.deepseek import AnalysisError, analyze_case, build_payload
from driving_school_rights.documents import DocumentError, extract_document, sanitize_text
from driving_school_rights.export import export_document
from driving_school_rights.guidance import CaseFacts, build_negotiation_plan, recommend_routes
from driving_school_rights.knowledge import get_contacts, load_contacts, load_laws, search_laws
from driving_school_rights.config import ConfigError, load_config


logger = logging.getLogger(__name__)
st.set_page_config(page_title="山东学车权益助手", page_icon="⚖️", layout="centered")
st.title("山东学车权益助手")
st.caption("帮你梳理驾校培训争议、准备协商方案、维权路径和文书草稿。")
st.warning("本工具提供一般法律信息和文书草稿，不代替律师、行政机关或法院作出法律结论。")
with st.expander("材料与隐私说明", expanded=True):
    st.write("首版不设账号，不保存服务器端聊天历史或上传原文件。解析仅在当前会话内存中进行；发送前会展示并允许编辑实际发送的摘录，只有你勾选确认并点击发送后才调用 DeepSeek。请先遮盖无关个人信息。第三方服务的数据处理受其账户配置和服务政策约束。")

try:
    config = load_config()
    config_error = None
except ConfigError as exc:
    config = None
    config_error = str(exc)

if config_error:
    st.info(config_error)

cities = ["济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽"]
issues = ["驾校违约/退费", "教练态度或教学问题", "培训安排/转校", "培训记录或课时争议", "其他"]

with st.form("case_intake"):
    city = st.selectbox("驾校所在地", cities, key="city")
    issue = st.selectbox("主要问题", issues, key="issue")
    description = st.text_area("简单描述发生了什么", max_chars=4000, key="description")
    amount_raw = st.text_input("你核实过的付款金额（元，可留空）", key="confirmed_amount")
    progress = st.text_input("培训进度（可留空）", key="training_progress")
    urgent = st.checkbox("目前存在正在发生的人身安全危险", key="urgent_safety_risk")
    case_submitted = st.form_submit_button("整理情况与建议")

if case_submitted:
    amount = None
    if amount_raw.strip():
        try:
            amount = float(amount_raw.strip())
            if amount < 0:
                raise ValueError
        except ValueError:
            st.error("付款金额请填写非负数字，或留空。")
            amount = None
    case = CaseFacts(issue, city, description.strip(), amount, urgent, training_progress=progress.strip())
    st.session_state["case_facts"] = case
    st.session_state.pop("analysis_result", None)

case = st.session_state.get("case_facts")
if case:
    st.subheader("先协商，再按问题选择渠道")
    plan = build_negotiation_plan(case)
    st.write(f"**第一步：** {plan.first_step}")
    st.write(f"**主要诉求：** {plan.primary_request}")
    st.write(f"**备选方案：** {plan.alternative}")
    with st.expander("准备证据清单"):
        for entry in plan.evidence:
            st.write(f"- {entry}")
    st.markdown("**常用维权路径（需根据具体事实选择）**")
    for route in recommend_routes(case):
        with st.expander(f"{route.channel}｜{route.when_to_use}"):
            st.write("办理步骤：" + "；".join(route.steps))
            st.write("准备材料：" + "；".join(route.prepare))
            st.caption(route.limitations)
    contacts = get_contacts(case.city, case.issue_type, load_contacts(), date.today())
    st.markdown("**官方联系方式**")
    for contact in contacts:
        if contact.unverified_local:
            st.caption(f"未核验到{case.city}市专属号码，以下为官方通用入口。")
            break
    for contact in contacts:
        st.write(f"**{contact.name}：{contact.phone or '在线入口'}** — {contact.scope}")
        if contact.website:
            st.markdown(f"[官方来源/入口]({contact.website})")
        st.caption(f"來源核验日期：{contact.verified_at.isoformat()}")

    st.subheader("上传合同、聊天记录等材料")
    uploads = st.file_uploader("支持 PDF、DOCX、TXT、PNG、JPG；文件仅在当前会话内存中处理", type=["pdf", "docx", "txt", "png", "jpg", "jpeg"], accept_multiple_files=True, max_upload_size=config.max_upload_mb if config else 10, key="evidence_uploads")
    if st.button("读取材料并进入校对", disabled=not uploads):
        extracted = []
        failures = []
        for uploaded in uploads:
            try:
                extracted.append(extract_document(uploaded.name, uploaded.getvalue(), config or _fallback_config()))
            except DocumentError as exc:
                failures.append(f"{uploaded.name}：{exc}")
        st.session_state["extracted_documents"] = extracted
        for failure in failures:
            st.error(failure)
        if extracted:
            st.success(f"已在内存中提取 {len(extracted)} 份材料，请核对识别文字。")

    excerpts = []
    for index, document in enumerate(st.session_state.get("extracted_documents", [])):
        st.markdown(f"**{document.filename}**（{document.file_type}）")
        if document.page_count is not None:
            st.caption(f"页数：{document.page_count}")
        if document.ocr_confidence is not None:
            st.caption(f"OCR 平均置信度：{document.ocr_confidence}%")
        for warning in document.warnings:
            st.warning(warning)
        edited = st.text_area("识别文字（可编辑）", value=document.text, height=180, key=f"edited_{index}", max_chars=15000)
        excerpts.append(f"【{document.filename}】\n{edited}")

    if excerpts:
        merged_excerpt = "\n\n".join(excerpts)
        redaction_values = st.text_input("选择遮盖的内容（多个内容用中文或英文逗号分隔）", key="redaction_values", help="例如电话号码、身份证号。遮盖只应用于下方展示并发送的摘录。")
        values = [item.strip() for item in redaction_values.replace("，", ",").split(",") if item.strip()]
        preview_excerpt = sanitize_text(merged_excerpt, values)
        st.markdown("**发送前预览**")
        st.caption("确认后，所在地、问题类型、你填写的案情描述/培训进度，以及下方材料摘录会一并发送给 DeepSeek。请检查上方表单和下方完整摘录。")
        st.code(preview_excerpt, language=None)
        consent_context = {
            "city": case.city if case else city,
            "issue": case.issue_type if case else issue,
            "description": case.description if case else description,
            "training_progress": case.training_progress if case else progress,
            "amount": case.confirmed_amount if case else None,
            "urgent": case.urgent_safety_risk if case else urgent,
            "excerpt": preview_excerpt,
        }
        consent_key = "confirm_send_" + hashlib.sha256(json.dumps(consent_context, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
        consent = st.checkbox("我已检查上方完整摘录，并确认将其发送给 DeepSeek 进行分析", key=consent_key)
        if st.button("确认并分析", disabled=not consent):
            if not config:
                st.error("尚未配置 DeepSeek API Key。请由部署管理员在服务端环境变量中配置后再分析。")
            else:
                try:
                    laws = search_laws(f"{case.description if case else ''} {preview}", case.issue_type if case else "", load_laws(), date.today())
                    active_case = case or CaseFacts("其他", None, "")
                    active_plan = build_negotiation_plan(active_case)
                    routes = recommend_routes(active_case)
                    payload = build_payload(active_case, preview_excerpt, laws, routes, active_plan)
                    from openai import OpenAI
                    result = analyze_case(OpenAI(api_key=config.api_key, base_url=config.api_base_url, timeout=60, max_retries=1), payload, config.model)
                    st.session_state["analysis_result"] = result
                    st.session_state["confirmed_excerpt"] = preview_excerpt
                except AnalysisError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    logger.warning("Analysis setup failed (%s)", type(exc).__name__)
                    st.error("无法连接分析服务，请稍后重试。")

result = st.session_state.get("analysis_result")
if result:
    st.subheader("分析结果（请核对事实与适用性）")
    st.markdown("**事实梳理**")
    st.write(result.fact_summary)
    if result.questions:
        st.markdown("**还需要补充**")
        for question in result.questions:
            st.write(f"- {question}")
    st.markdown("**法规依据**")
    if result.legal_basis:
        for law in result.legal_basis:
            st.write(f"{law.get('title', '')} {law.get('article', '')}：{law.get('summary', '')}")
            if law.get("source_url"):
                st.markdown(f"[官方来源]({law['source_url']})")
    else:
        st.info("未检索到已核验的匹配法条；具体依据尚待核实。")
    st.markdown("**协商建议**")
    st.write(result.negotiation)
    for uncertainty in result.uncertainties:
        st.warning(uncertainty)
    st.subheader("生成可编辑文书")
    doc_type = st.selectbox("文书类型", ["协商函", "退费/解除合同请求", "12328情况反映稿", "12315投诉稿"], key="doc_type")
    for kind, mime, extension in [("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"), ("txt", "text/plain; charset=utf-8", "txt")]:
        data = export_document(result, kind, doc_type)
        st.download_button(f"下载 {kind.upper()}", data, file_name=f"{doc_type}.{extension}", mime=mime, key=f"download_{kind}")

if st.button("清除本次材料和分析"):
    for key in ("extracted_documents", "analysis_result", "confirmed_excerpt", "case_facts", "send_preview", "redaction_values", "confirm_send"):
        st.session_state.pop(key, None)
    st.rerun()


def _fallback_config():
    from driving_school_rights.config import AppConfig
    return AppConfig("", "", "", 10, 30, 15000, 5, 100)


def main():
    """Streamlit entry point; UI is rendered by module execution."""
