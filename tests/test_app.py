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


def test_submitted_case_details_follow_next_chat_question(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    seen = []

    def fake_analysis(client, payload, model):
        seen.append(payload)
        return AssistantResult("待核实", [], [], "先联系驾校", [], {}, [])

    monkeypatch.setattr("driving_school_rights.deepseek.analyze_case", fake_analysis)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint).run()
    app.selectbox[0].set_value("青岛")
    app.text_area[0].set_value("驾校取消了三次预约")
    next(box for box in app.text_input if "付款金额" in box.label).set_value("2800")
    next(box for box in app.text_input if "培训进度" in box.label).set_value("科目二")
    next(button for button in app.button if button.label == "更新情况与建议").click().run()
    app.chat_input[0].set_value("现在如何协商？").run()
    assert not app.exception
    assert len(seen) == 1
    assert '"confirmed_amount": 2800.0' in seen[0][1]["content"]
    assert '"training_progress": "科目二"' in seen[0][1]["content"]
    assert '"city": "青岛"' in seen[0][1]["content"]
    assert "驾校取消了三次预约" in seen[0][1]["content"]


def test_long_case_description_does_not_hide_latest_question(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda **kwargs: object()
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    seen = []

    def fake_analysis(client, payload, model):
        seen.append(payload[1]["content"])
        return AssistantResult("待核实", [], [], "先联系驾校", [], {}, [])

    monkeypatch.setattr("driving_school_rights.deepseek.analyze_case", fake_analysis)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint)
    app.session_state["form_case_facts"] = CaseFacts("其他", None, "旧案情" * 1400)
    app.run()
    app.chat_input[0].set_value("我刚才的问题是换教练，怎么办？").run()
    assert not app.exception
    assert "我刚才的问题是换教练" in seen[0]


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


def test_editing_uploaded_excerpt_requires_fresh_consent(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint)
    app.session_state["case_facts"] = CaseFacts("其他", None, "驾校争议")
    app.session_state["extracted_documents"] = [ExtractedDocument("记录.txt", "txt", "原始摘录")]
    app.run()
    next(box for box in app.checkbox if "确认将其发送给 DeepSeek" in box.label).set_value(True).run()
    assert next(button for button in app.button if button.label == "确认并分析").disabled is False
    next(box for box in app.text_area if "识别文字" in box.label).set_value("修改后的摘录").run()
    assert not app.exception
    assert next(button for button in app.button if button.label == "确认并分析").disabled is True


def test_text_only_case_does_not_require_upload_confirmation(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint)
    app.session_state["case_facts"] = CaseFacts("其他", None, "没有合同，驾校不退费")
    app.run()
    assert not app.exception
    assert not any(button.label == "确认并分析" for button in app.button)


def test_clear_button_removes_chat_and_uploaded_text(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    entrypoint = Path(__file__).parents[1] / "driving_school_rights" / "app.py"
    app = AppTest.from_file(entrypoint)
    app.session_state["case_facts"] = CaseFacts("其他", None, "私人案情")
    app.session_state["chat_messages"] = [{"role": "user", "content": "私人案情"}]
    app.session_state["extracted_documents"] = [ExtractedDocument("合同.txt", "txt", "私人材料")]
    app.session_state["analysis_calls"] = 2
    app.session_state["form_case_facts"] = CaseFacts("其他", None, "私人补充信息")
    app.run()
    next(button for button in app.button if button.label == "清除本次材料和分析").click().run()
    assert not app.exception
    assert not app.session_state.get("chat_messages")
    assert not app.session_state.get("extracted_documents")
    assert not app.session_state.get("form_case_facts")
    assert app.session_state["analysis_calls"] == 2

