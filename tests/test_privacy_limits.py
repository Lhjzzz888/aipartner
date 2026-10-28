from datetime import date
import logging

import pytest

from driving_school_rights.config import AppConfig
from driving_school_rights.limits import BudgetError, check_request_budget, clear_case_state


def _config(session=5, daily=100):
    return AppConfig("secret", "https://api.deepseek.com", "deepseek-flash", 10, 30, 15000, session, daily)


def test_clear_case_state_removes_sensitive_fields():
    state = {"case_facts": "private", "analysis_result": "answer", "extracted_documents": ["upload"], "other": "keep"}
    clear_case_state(state)
    assert state == {"other": "keep"}


def test_session_budget_blocks_excess_calls():
    state = {}
    check_request_budget(state, _config(session=1), today=date(2026, 10, 28))
    with pytest.raises(BudgetError):
        check_request_budget(state, _config(session=1), today=date(2026, 10, 28))


def test_daily_budget_blocks_excess_calls():
    state = {}
    check_request_budget(state, _config(daily=1), today=date(2026, 10, 29))
    with pytest.raises(BudgetError):
        check_request_budget(state, _config(daily=1), today=date(2026, 10, 29))


def test_logging_never_includes_uploaded_text_or_api_key(caplog):
    from driving_school_rights.deepseek import analyze_case, AnalysisError
    from types import SimpleNamespace

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret key and sensitive document")))))
    with caplog.at_level(logging.WARNING):
        with pytest.raises(AnalysisError):
            analyze_case(client, [{"role": "user", "content": "sensitive document"}], "deepseek-chat")
    assert "secret key" not in caplog.text
    assert "sensitive document" not in caplog.text
