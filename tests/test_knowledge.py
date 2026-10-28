from datetime import date

from driving_school_rights.knowledge import ContactRecord, load_contacts, load_laws, search_laws, get_contacts


def test_search_laws_filters_inactive_and_has_sources():
    laws = load_laws()
    results = search_laws("驾校退费违约", "退款", laws, date(2026, 10, 28))
    assert results
    assert all(item.source_url.startswith("https://") and item.verified_at for item in results)
    assert all(item.effective_from <= date(2026, 10, 28) for item in results)


def test_no_law_match_returns_empty():
    assert search_laws("太空采矿", "其他", [], date(2026, 10, 28)) == []


def test_missing_contract_and_12315_question_retrieves_current_process_rules():
    results = search_laws("没有合同怎么12315投诉", "驾校违约/退费", load_laws(), date(2026, 10, 28))
    ids = {law.id for law in results}
    assert "driver-training-2026-art-27" in ids
    assert "samr-complaints-2026-art-10" in ids
    assert "12328-hotline-2021-art-2" in ids


def test_contacts_fallback_without_inventing_local_number():
    result = get_contacts("不存在城市", "退款", load_contacts(), date(2026, 10, 28))
    assert result
    assert all(item.is_official for item in result)
    assert any(item.unverified_local for item in result)
    assert all(item.phone not in {"", None} or item.website for item in result)


def test_contacts_hide_stale_records():
    stale = ContactRecord("某市交通运输部门", "", "https://gov.example", "transport", date(2020, 1, 1), date(2020, 1, 1), True, "某市")
    assert get_contacts("某市", "退款", [stale], date(2026, 10, 28)) == []

