"""In-memory request quotas and sensitive session-state cleanup."""

from datetime import date
from threading import Lock


class BudgetError(ValueError):
    """Raised when the configured analysis request budget is exhausted."""


_lock = Lock()
_daily_date = None
_daily_count = 0


def check_request_budget(session_state, config, today=None):
    global _daily_date, _daily_count
    today = today or date.today()
    session_count = int(session_state.get("analysis_calls", 0))
    if session_count >= config.max_calls_per_session:
        raise BudgetError("本次会话的分析次数已达到上限。")
    with _lock:
        if _daily_date != today:
            _daily_date = today
            _daily_count = 0
        if _daily_count >= config.max_calls_per_day:
            raise BudgetError("当前服务的每日分析次数已达到上限，请稍后再试。")
        _daily_count += 1
    session_state["analysis_calls"] = session_count + 1


def clear_case_state(session_state):
    sensitive_keys = {
        "case_facts", "analysis_result", "extracted_documents", "confirmed_excerpt",
        "send_preview", "redaction_values", "confirm_send", "description",
        "confirmed_amount", "training_progress", "urgent_safety_risk", "evidence_uploads",
        "city", "issue", "edited_0", "doc_type",
        "description", "confirmed_amount", "training_progress", "urgent_safety_risk",
        "city", "issue", "edited_0", "doc_type",
    }
    for key in sensitive_keys:
        session_state.pop(key, None)
    for key in list(session_state.keys()):
        if key.startswith(("confirm_send_", "edited_")):
            session_state.pop(key, None)
