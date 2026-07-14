"""search_precedent.py 단위 테스트."""

import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "legal-kr" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import search_precedent  # noqa: E402


# ---------------------------------------------------------------------------
# make_citation / match_court / sort_results
# ---------------------------------------------------------------------------

def test_make_citation():
    entry = {"법원명": "대법원", "선고일자": "2025-08-14", "사건번호": "2024다227606"}
    assert search_precedent.make_citation(entry) == "대법원 2025. 8. 14. 선고 2024다227606 판결"


def test_match_court_대법원():
    assert search_precedent.match_court({"법원명": "대법원"}, "대법원")
    assert not search_precedent.match_court({"법원명": "서울고등법원"}, "대법원")


def test_match_court_하급심():
    assert search_precedent.match_court({"법원명": "서울중앙지방법원", "path": "민사/하급심/x.md"}, "하급심")
    assert not search_precedent.match_court({"법원명": "대법원", "path": "민사/대법원/x.md"}, "하급심")


def test_sort_results_supreme_court_first_then_recent():
    results = [
        {"법원명": "서울고등법원", "선고일자": "2025-01-01"},
        {"법원명": "대법원", "선고일자": "2020-01-01"},
        {"법원명": "대법원", "선고일자": "2024-01-01"},
    ]
    ordered = search_precedent.sort_results(results)
    assert ordered[0]["선고일자"] == "2024-01-01"
    assert ordered[1]["선고일자"] == "2020-01-01"
    assert ordered[2]["법원명"] == "서울고등법원"


# ---------------------------------------------------------------------------
# extract_sections
# ---------------------------------------------------------------------------

SAMPLE_CASE = textwrap.dedent("""\
    # 손해배상(기)

    ## 판시사항
    불법행위 손해배상 책임의 성립 요건

    ## 판결요지
    고의 또는 과실로 인한 위법행위로 타인에게 손해를 가한 자는 그 손해를 배상할 책임이 있다.

    ## 참조조문
    민법 제750조

    ## 판례내용
    전문 텍스트...
    """)


def test_extract_sections(tmp_path):
    f = tmp_path / "case.md"
    f.write_text(SAMPLE_CASE, encoding="utf-8")
    sections = search_precedent.extract_sections(str(f), ["판시사항", "판결요지", "참조조문"])
    assert "불법행위" in sections["판시사항"]
    assert "배상할 책임" in sections["판결요지"]
    assert "민법 제750조" in sections["참조조문"]


# ---------------------------------------------------------------------------
# search_by_case (--case 직접 조회)
# ---------------------------------------------------------------------------

METADATA = {
    "100": {"사건명": "손해배상(기)", "사건번호": "2024다1234", "선고일자": "2025-01-01",
            "법원명": "대법원", "사건종류": "민사", "path": "민사/대법원/2024다1234.md"},
    "200": {"사건명": "임대차보증금·부당이득금", "사건번호": "2024다227606, 227620",
            "선고일자": "2025-08-14", "법원명": "대법원", "사건종류": "민사",
            "path": "민사/대법원/2024다227606_227620.md"},
    "300": {"사건명": "손해배상(자)", "사건번호": "2024다12345", "선고일자": "2025-02-01",
            "법원명": "대법원", "사건종류": "민사", "path": "민사/대법원/2024다12345.md"},
}


def test_search_by_case_exact():
    results = search_precedent.search_by_case(METADATA, "2024다1234")
    assert len(results) == 1
    assert results[0]["id"] == "100"


def test_search_by_case_exact_does_not_prefix_match():
    """'2024다1234'가 '2024다12345'에 부분 일치로 잘못 걸리면 안 된다."""
    results = search_precedent.search_by_case(METADATA, "2024다1234")
    assert all(r["id"] != "300" for r in results)


def test_search_by_case_combined_number():
    """병합 사건번호('2024다227606, 227620')의 후행 번호로도 조회 가능해야 한다."""
    results = search_precedent.search_by_case(METADATA, "227620")
    assert len(results) == 1
    assert results[0]["id"] == "200"


def test_search_by_case_not_found():
    assert search_precedent.search_by_case(METADATA, "9999다9999") == []
