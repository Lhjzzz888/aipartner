from pathlib import Path
import subprocess
import sys

from streamlit.testing.v1 import AppTest


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
    app.button[0].click().run()
    assert not app.exception
    assert any("先协商" in heading.value for heading in app.subheader)
    assert any("12328" in expander.label for expander in app.expander)

