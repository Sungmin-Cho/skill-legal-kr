"""search_precedent.py 단위 테스트."""

import json
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


# ---------------------------------------------------------------------------
# metadata 인덱스 자동 생성 (precedent-kr은 metadata.json을 git으로 배포하지 않음)
# ---------------------------------------------------------------------------

def _case_file(repo, rel, serial, case_no, name, court="대법원", kind="형사", date="1986-02-11"):
    fp = repo / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(textwrap.dedent(f"""\
        ---
        판례일련번호: '{serial}'
        사건번호: {case_no}
        사건명: {name}
        법원명: {court}
        법원등급: {'대법원' if court == '대법원' else '하급심'}
        사건종류: {kind}
        출처: https://www.law.go.kr/LSW/precInfoP.do?precSeq={serial}
        첨부파일: []
        선고일자: {date}
        ---

        ## 판시사항
        군무이탈죄에 있어서의 군무기피의 목적

        ## 참조조문
        군형법 제30조
        """), encoding="utf-8")
    return fp


@pytest.fixture
def fake_repo(tmp_path):
    repo = tmp_path / "precedent-kr"
    (repo).mkdir()
    (repo / "README.md").write_text("# readme\n", encoding="utf-8")
    _case_file(repo, "형사/대법원/대법원_1986-02-11_85도2674.md", "100001", "85도2674", "군무이탈")
    _case_file(repo, "형사/하급심/서울고등법원_2020-01-01_2019노1.md", "100002", "2019노1",
               "상해", court="서울고등법원", date="2020-01-01")
    return repo


def test_parse_frontmatter_strips_quotes(fake_repo):
    fm = search_precedent.parse_frontmatter(fake_repo / "형사/대법원/대법원_1986-02-11_85도2674.md")
    assert fm["판례일련번호"] == "100001"
    assert fm["사건번호"] == "85도2674"
    assert fm["선고일자"] == "1986-02-11"


def test_parse_frontmatter_without_frontmatter(tmp_path):
    f = tmp_path / "x.md"
    f.write_text("# 제목만 있는 파일\n", encoding="utf-8")
    assert search_precedent.parse_frontmatter(f) == {}


def test_build_metadata_uses_posix_paths_and_skips_readme(fake_repo):
    meta = search_precedent.build_metadata(str(fake_repo))
    assert set(meta) == {"100001", "100002"}
    assert meta["100001"]["path"] == "형사/대법원/대법원_1986-02-11_85도2674.md"
    assert meta["100001"]["법원명"] == "대법원"
    assert meta["100002"]["사건종류"] == "형사"


def test_load_metadata_builds_and_caches(fake_repo, monkeypatch):
    monkeypatch.setattr(search_precedent, "git_head", lambda repo: "abc123")
    meta = search_precedent.load_metadata(str(fake_repo))
    assert "100001" in meta and search_precedent.INDEX_KEY not in meta
    assert (fake_repo / "metadata.json").exists()
    stats = json.loads((fake_repo / "stats.json").read_text(encoding="utf-8"))
    assert stats["total"] == 2 and stats["법원등급"] == {"대법원": 1, "하급심": 1}

    # 같은 HEAD면 캐시를 그대로 쓴다 (다시 만들지 않음)
    monkeypatch.setattr(search_precedent, "build_metadata", lambda repo: pytest.fail("rebuilt"))
    assert "100002" in search_precedent.load_metadata(str(fake_repo))


def test_load_metadata_rebuilds_when_head_changes(fake_repo, monkeypatch):
    monkeypatch.setattr(search_precedent, "git_head", lambda repo: "old")
    search_precedent.load_metadata(str(fake_repo))
    _case_file(fake_repo, "형사/대법원/대법원_1995-07-11_95도910.md", "100003", "95도910", "군무이탈",
               date="1995-07-11")
    monkeypatch.setattr(search_precedent, "git_head", lambda repo: "new")
    assert "100003" in search_precedent.load_metadata(str(fake_repo))


def test_load_metadata_keeps_user_provided_file(fake_repo, monkeypatch):
    """인덱스 정보가 없는(직접 넣은) metadata.json은 덮어쓰지 않는다."""
    monkeypatch.setattr(search_precedent, "git_head", lambda repo: "abc123")
    (fake_repo / "metadata.json").write_text(json.dumps(METADATA, ensure_ascii=False), encoding="utf-8")
    assert search_precedent.load_metadata(str(fake_repo)) == METADATA


def test_load_metadata_missing_repo(tmp_path):
    assert search_precedent.load_metadata(str(tmp_path / "없음")) == {}


def test_relative_posix(fake_repo):
    fp = fake_repo / "형사" / "대법원" / "대법원_1986-02-11_85도2674.md"
    assert search_precedent.relative_posix(str(fp), str(fake_repo)) == "형사/대법원/대법원_1986-02-11_85도2674.md"
    assert search_precedent.relative_posix(str(fp), str(fake_repo / "민사")) is None


def test_main_prints_empty_list_when_no_data(tmp_path, monkeypatch, capsys):
    """데이터가 없을 때 빈 JSON 배열을 출력하고 예외 없이 끝나야 한다."""
    monkeypatch.setattr(sys, "argv", ["search_precedent.py", "--repo", str(tmp_path / "없음"), "--case", "1"])
    search_precedent.main()
    assert capsys.readouterr().out.strip() == "[]"
