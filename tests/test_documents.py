from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from PIL import Image

from driving_school_rights.config import AppConfig
from driving_school_rights import documents


def _config(**overrides):
    values = {
        "api_key": "test-key",
        "api_base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "max_upload_mb": 10,
        "max_pdf_pages": 30,
        "max_text_chars": 15000,
        "max_calls_per_session": 5,
        "max_calls_per_day": 100,
    }
    values.update(overrides)
    return AppConfig(**values)


def _pdf_with_text(text="PDF evidence sample"):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(content)
    content += f"xref\n0 {len(offsets)}\n".encode()
    content += b"0000000000 65535 f \n"
    content += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    content += (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return content


def _blank_pdf():
    return _pdf_with_text("")


def test_extracts_text_pdf():
    result = documents.extract_document("evidence.pdf", _pdf_with_text(), _config())

    assert result.file_type == "pdf"
    assert result.text == "PDF evidence sample"
    assert result.page_count == 1
    assert result.ocr_confidence is None


def test_extracts_text_docx():
    doc = Document()
    doc.add_paragraph("驾校培训合同约定课时")
    buffer = BytesIO()
    doc.save(buffer)

    result = documents.extract_document("contract.docx", buffer.getvalue(), _config())

    assert "驾校培训合同约定课时" in result.text
    assert result.file_type == "docx"


def test_extracts_text_txt_with_chinese_encoding():
    content = "教练临时取消了预约".encode("gb18030")

    result = documents.extract_document("chat.txt", content, _config())

    assert result.text == "教练临时取消了预约"
    assert result.file_type == "txt"


def test_ocr_image_chinese_and_reports_confidence(monkeypatch):
    image_bytes = BytesIO()
    Image.new("RGB", (16, 16), "white").save(image_bytes, format="PNG")
    monkeypatch.setattr(
        documents.pytesseract,
        "image_to_data",
        lambda image, lang, output_type: {
            "text": ["驾校聊天记录", "退费"],
            "conf": ["91", "83"],
        },
    )

    result = documents.extract_document("chat.png", image_bytes.getvalue(), _config())

    assert "驾校聊天记录 退费" == result.text
    assert result.ocr_confidence == 87.0
    assert any("OCR" in warning for warning in result.warnings)


def test_scanned_pdf_uses_ocr(monkeypatch):
    monkeypatch.setattr(
        documents.pytesseract,
        "image_to_data",
        lambda image, lang, output_type: {"text": ["扫描合同条款"], "conf": ["86"]},
    )

    result = documents.extract_document("scan.pdf", _blank_pdf(), _config())

    assert result.page_count == 1
    assert result.text == "扫描合同条款"
    assert result.ocr_confidence == 86.0


def test_rejects_oversize_and_corrupt_files():
    with pytest.raises(documents.DocumentError, match="文件大小"):
        documents.extract_document("large.txt", b"x" * (1024 * 1024 + 1), _config(max_upload_mb=1))

    with pytest.raises(documents.DocumentError, match="PDF"):
        documents.extract_document("broken.pdf", b"not a pdf", _config())


def test_sanitize_text_masks_user_selected_values():
    result = documents.sanitize_text(
        "学员13800138000向驾校付款。",
        ["13800138000"],
    )

    assert result == "学员[已遮盖]向驾校付款。"


def test_extract_truncates_long_text_with_warning():
    result = documents.extract_document("note.txt", b"abcdef", _config(max_text_chars=4))

    assert result.text == "abcd"
    assert any("长度上限" in warning for warning in result.warnings)
