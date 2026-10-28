from pathlib import Path
import subprocess
import sys
from types import ModuleType

from streamlit.testing.v1 import AppTest

from driving_school_rights.deepseek import AnalysisError, AssistantResult
from driving_school_rights.documents import ExtractedDocument
from driving_school_rights.guidance import CaseFacts


def test_home_shows_privacy_boundary_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"

    app = AppTest.from_file(entrypoint).run()

    assert not app.exception
    assert any(title.value == "山东学车权益助手" for title in app.title)
    assert any("不代替律师" in warning.value for warning in app.warning)
    assert any("DEEPSEEK_API_KEY" in info.value for info in app.info)


def test_entrypoint_renders_when_started_outside_repository_root():
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    code = (
        "from streamlit.testing.v1 import AppTest; "
        f"app = AppTest.from_file({str(entrypoint)!r}).run(); "
        "assert not app.exception, [str(error.message) for error in app.exception]; "
        "assert any(title.value == '山东学车权益助手' for title in app.title)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=entrypoint.parents[1] / "tests",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_case_intake_renders_routes_without_calling_api(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint).run()
    app.text_area[0].set_value("驾校连续取消预约，想了解退费流程")
    next(button for button in app.button if button.label == "更新情况与建议").click().run()
    assert not app.exception
    assert any("详细方案" in heading.value for heading in app.subheader)
    assert any("12328" in item.value for item in app.markdown)


def test_no_contract_question_works_without_upload_or_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint).run()
    next(button for button in app.button if "我没有合同" in button.label).click().run()
    assert not app.exception
    assert any("没有合同也可以先处理" in item.value for item in app.markdown)
    assert app.session_state["case_facts"].description == "我没有合同，怎么退费？"
    assert not app.session_state.get("extracted_documents")


def test_chat_input_accepts_question_without_documents(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint).run()
    app.chat_input[0].set_value("我没留证据，教练态度很差").run()
    assert not app.exception
    assert "没留证据，先从今天开始补" in app.session_state["chat_messages"][-1]["content"]


def test_chat_question_calls_deepseek_immediately(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    seen = []

    def fake_analysis(client, payload, model):
        seen.append(payload)
        return AssistantResult("针对本次提问的事实整理", ["付款时间是什么时候？"], [], "先书面联系驾校", [], {}, [])

    monkeypatch.setattr("driving_school_rights.deepseek.analyze_case", fake_analysis)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint).run()
    app.chat_input[0].set_value("教练态度差，我没证据怎么办？").run()
    assert not app.exception
    assert len(seen) == 1
    assert "教练态度差" in seen[0][1]["content"]
    assert "针对本次提问的事实整理" in app.session_state["chat_messages"][-1]["content"]


def test_confirmed_evidence_reaches_analysis(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    def stop_before_network(*args):
        raise AnalysisError("已进入分析步骤")

    monkeypatch.setattr("driving_school_rights.deepseek.analyze_case", stop_before_network)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint)
    app.session_state["case_facts"] = CaseFacts("驾校违约/退费", "济南", "预约课程被取消")
    app.session_state["extracted_documents"] = [
        ExtractedDocument("合同.txt", "txt", "驾校承诺按时安排训练")
    ]

    app.run()
    next(box for box in app.checkbox if "确认将其发送给 DeepSeek" in box.label).set_value(True).run()
    next(button for button in app.button if button.label == "确认并分析").click().run()

    assert not app.exception
    assert any("已进入分析步骤" in error.value for error in app.error)


def test_text_only_case_does_not_require_upload_confirmation(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint)
    app.session_state["case_facts"] = CaseFacts("其他", None, "没有合同，驾校不退费")
    app.run()
    assert not app.exception
    assert not any(button.label == "确认并分析" for button in app.button)

