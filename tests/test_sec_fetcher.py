"""Tests for sec_fetcher — SEC EDGAR filing text downloader."""

import pytest
from xueqiu_analyzer.sec_fetcher import (
    extract_accession,
    extract_form_type,
    is_high_value_filing,
    HIGH_VALUE_FORMS,
)


# ── extract_accession ────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    # Standard 6-K
    (
        "6-K Report of foreign issuer [Rules 13a-16 and 15d-16] "
        "Accession Number: 0001104659-26-067186 Act: 34 Size: 212 KB",
        "0001104659-26-067186",
    ),
    # 20-F
    (
        "20-F Annual and transition report of foreign private issuers "
        "[Sections 13 or 15(d)] Accession Number: 0001104659-26-050727 Act: 34 Size: 15 MB",
        "0001104659-26-050727",
    ),
    # Form 4
    (
        "4 Statement of changes in beneficial ownership of securities "
        "Accession Number: 0001104659-26-038207 Size: 5 KB",
        "0001104659-26-038207",
    ),
    # Form 144
    (
        "144 Report of proposed sale of securities "
        "Accession Number: 0001973379-26-000126 Act: 33 Size: 4 KB",
        "0001973379-26-000126",
    ),
])
def test_extract_accession_from_sec_title(title, expected):
    assert extract_accession(title) == expected


@pytest.mark.parametrize("title", [
    "MANYCORE TECH 月报表 截至二零二六年五月三十一日止月份之股份发行人的证券变动月报表",
    "贵州茅台：关于召开2025年度股东大会的通知",
    "",  # empty
    "No accession number here",
])
def test_extract_accession_returns_none(title):
    assert extract_accession(title) is None


# ── extract_form_type ────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("6-K Report of foreign issuer ...", "6-K"),
    ("20-F Annual and transition report ...", "20-F"),
    ("4 Statement of changes ...", "4"),
    ("144 Report of proposed sale ...", "144"),
    ("8-K Current report ...", "8-K"),
    ("10-K Annual report ...", "10-K"),
    ("10-Q Quarterly report ...", "10-Q"),
    ("S-1 Registration statement ...", "S-1"),
])
def test_extract_form_type(title, expected):
    assert extract_form_type(title) == expected


@pytest.mark.parametrize("title", [
    "贵州茅台：关于召开...",
    "",
    "  6-K Report...",  # leading space — won't match ^
])
def test_extract_form_type_returns_none(title):
    assert extract_form_type(title) is None


# ── is_high_value_filing ─────────────────────────────────────

@pytest.mark.parametrize("title", [
    "6-K Report of foreign issuer ... Accession Number: 0001104659-26-067186",
    "20-F Annual and transition report ... Accession Number: 0001104659-26-050727",
    "8-K Current report ... Accession Number: 0001104659-26-123456",
    "10-K Annual report ... Accession Number: 0001104659-26-111111",
    "10-Q Quarterly report ... Accession Number: 0001104659-26-222222",
])
def test_is_high_value_filing_true(title):
    assert is_high_value_filing(title) is True


@pytest.mark.parametrize("title", [
    "4 Statement of changes ... Accession Number: 0001104659-26-038207",
    "144 Report of proposed sale ... Accession Number: 0001973379-26-000126",
    "3 Initial statement ... Accession Number: 0001104659-26-031565",
    "S-1 Registration statement ... Accession Number: 0001104659-26-999999",
    "MANYCORE TECH 月报表 ...",  # HK stock
    "贵州茅台：关于召开...",  # A-share
    "",  # empty
])
def test_is_high_value_filing_false(title):
    assert is_high_value_filing(title) is False


# ── HIGH_VALUE_FORMS constant ─────────────────────────────────

def test_high_value_forms_contains_expected():
    assert '6-K' in HIGH_VALUE_FORMS
    assert '20-F' in HIGH_VALUE_FORMS
    assert '8-K' in HIGH_VALUE_FORMS
    assert '10-K' in HIGH_VALUE_FORMS
    assert '10-Q' in HIGH_VALUE_FORMS


def test_high_value_forms_excludes_low_value():
    assert '4' not in HIGH_VALUE_FORMS
    assert '3' not in HIGH_VALUE_FORMS
    assert '144' not in HIGH_VALUE_FORMS
    assert 'S-1' not in HIGH_VALUE_FORMS


# ── extract_file_size ────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("6-K ... Size: 212 KB", "212 KB"),
    ("20-F ... Size: 15 MB", "15 MB"),
    ("4 ... Size: 5 KB", "5 KB"),
    ("144 ... Size: 4 KB", "4 KB"),
    ("3 ... Size: 10 KB", "10 KB"),
])
def test_extract_file_size(title, expected):
    from xueqiu_analyzer.sec_fetcher import extract_file_size
    assert extract_file_size(title) == expected


def test_extract_file_size_returns_empty():
    from xueqiu_analyzer.sec_fetcher import extract_file_size
    assert extract_file_size("No size here") == ""
    assert extract_file_size("") == ""


# ── build_sec_url ────────────────────────────────────────────

def test_build_sec_url():
    from xueqiu_analyzer.sec_fetcher import build_sec_url
    url = build_sec_url("0001104659-26-067186")
    assert "sec.gov" in url
    assert "1104659" in url
    assert "000110465926067186" in url
    assert "0001104659-26-067186-index.htm" in url
    assert url.startswith("https://www.sec.gov/Archives/edgar/data/")


# ── build_sec_summary ────────────────────────────────────────

REAL_6K_TITLE = (
    "6-K Report of foreign issuer [Rules 13a-16 and 15d-16] "
    "Accession Number: 0001104659-26-067186 Act: 34 Size: 212 KB"
)


def test_build_sec_summary_contains_key_fields():
    from xueqiu_analyzer.sec_fetcher import build_sec_summary
    summary = build_sec_summary(REAL_6K_TITLE, "2026-05-28T10:25:01.000Z")
    assert "[SEC Filing] 6-K" in summary
    assert "Accession Number: 0001104659-26-067186" in summary
    assert "Filing Date: 2026-05-28" in summary
    assert "File Size: 212 KB" in summary
    assert "sec.gov" in summary


def test_build_sec_summary_no_date():
    from xueqiu_analyzer.sec_fetcher import build_sec_summary
    summary = build_sec_summary(REAL_6K_TITLE, "")
    assert "Accession Number" in summary
    assert "Filing Date" not in summary


def test_build_sec_summary_non_sec_title():
    from xueqiu_analyzer.sec_fetcher import build_sec_summary
    summary = build_sec_summary("MANYCORE TECH 月报表 ...", "")
    assert "Accession Number" not in summary
    assert "sec.gov" not in summary
    assert "[SEC Filing]" in summary  # still wrapped


# ── _clean_sec_text ──────────────────────────────────────────

def test_clean_sec_text_strips_html():
    from xueqiu_analyzer.sec_fetcher import _clean_sec_text
    dirty = "<html><body><p>Hello world</p></body></html>"
    result = _clean_sec_text(dirty)
    assert "Hello world" in result
    assert "<html>" not in result


def test_clean_sec_text_compresses_blank_lines():
    from xueqiu_analyzer.sec_fetcher import _clean_sec_text
    dirty = "Line1\n\n\n\n\nLine2"
    result = _clean_sec_text(dirty)
    # 4 blank lines → compressed to 2
    assert "\n\n\n\n" not in result


def test_clean_sec_text_handles_empty():
    from xueqiu_analyzer.sec_fetcher import _clean_sec_text
    assert _clean_sec_text("") == ""
    assert _clean_sec_text("   ") == ""


# ── _get_edgar_identity ──────────────────────────────────────

def test_get_edgar_identity_returns_string():
    from xueqiu_analyzer.sec_fetcher import _get_edgar_identity
    identity = _get_edgar_identity()
    assert isinstance(identity, str)
    assert '@' in identity
