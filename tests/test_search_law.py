"""search_law.py 단위 테스트."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "legal-kr" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import search_law  # noqa: E402


# ---------------------------------------------------------------------------
# detect_doc_type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename, expected", [
    ("법률.md", "법률"),
    ("시행령.md", "시행령"),
    ("대통령령.md", "대통령령"),          # 버그: 시행령으로 오분류되던 케이스
    ("총리령.md", "시행규칙"),            # 버그: 기타로 분류되어 필터 불가하던 케이스
    ("법무부령.md", "시행규칙"),
    ("시행규칙(국토교통부령).md", "시행규칙"),
    ("대법원규칙.md", "시행규칙"),
    ("고시.md", "기타"),
])
def test_detect_doc_type(filename, expected):
    assert search_law.detect_doc_type(filename) == expected


# ---------------------------------------------------------------------------
# parse_frontmatter / extract_article / make_snippet
# ---------------------------------------------------------------------------

SAMPLE_LAW = textwrap.dedent("""\
    ---
    제목: 테스트법률
    법령MST: 12345
    법령구분: 법률
    소관부처:
      - 법무부
      - 행정안전부
    공포일자: 2024-01-02
    상태: 시행
    출처: https://www.law.go.kr/법령/테스트법률
    ---

    # 테스트법률

    ## 제1장 총칙

    ##### 제1조(목적)
    이 법은 테스트를 목적으로 한다.

    ##### 제2조(정의)
    이 법에서 사용하는 용어의 뜻은 다음과 같다.

    ##### 제3조(보증금의 회수)
    보증금 회수에 관한 조문이다.

    ## 부칙
    이 법은 공포한 날부터 시행한다.
    """)


def test_parse_frontmatter():
    meta = search_law.parse_frontmatter(SAMPLE_LAW)
    assert meta["제목"] == "테스트법률"
    assert meta["상태"] == "시행"
    assert meta["소관부처"] == ["법무부", "행정안전부"]


def test_extract_article_by_number():
    text = search_law.extract_article(SAMPLE_LAW, "제2조")
    assert "정의" in text
    assert "제3조" not in text


def test_extract_article_stops_before_부칙():
    text = search_law.extract_article(SAMPLE_LAW, "제3조")
    assert "보증금 회수" in text
    assert "부칙" not in text


def test_extract_article_by_title():
    text = search_law.extract_article(SAMPLE_LAW, "보증금의 회수")
    assert "제3조" in text


def test_extract_article_missing():
    assert search_law.extract_article(SAMPLE_LAW, "제99조") is None


# ---------------------------------------------------------------------------
# 검색 함수 (fixture 저장소)
# ---------------------------------------------------------------------------

REPEALED_LAW = textwrap.dedent("""\
    ---
    제목: 폐지된법률
    법령구분: 법률
    상태: 폐지
    ---

    # 폐지된법률

    ##### 제1조(목적)
    폐지된 조문.
    """)

DECREE = textwrap.dedent("""\
    ---
    제목: 독립규정
    법령구분: 대통령령
    상태: 시행
    ---

    # 독립규정

    ##### 제1조(목적)
    독립 대통령령 조문.
    """)


@pytest.fixture
def repo(tmp_path):
    kr = tmp_path / "kr"
    (kr / "테스트법률").mkdir(parents=True)
    (kr / "테스트법률" / "법률.md").write_text(SAMPLE_LAW, encoding="utf-8")
    (kr / "폐지된법률").mkdir()
    (kr / "폐지된법률" / "법률.md").write_text(REPEALED_LAW, encoding="utf-8")
    (kr / "독립규정").mkdir()
    (kr / "독립규정" / "대통령령.md").write_text(DECREE, encoding="utf-8")
    return str(tmp_path)


def test_search_by_name_finds_law(repo):
    results = search_law.search_by_name(repo, "테스트", None, 10)
    assert len(results) == 1
    assert results[0]["법령명"] == "테스트법률"


def test_search_by_name_excludes_repealed_by_default(repo):
    results = search_law.search_by_name(repo, "폐지된", None, 10)
    assert results == []


def test_search_by_name_include_repealed_flag(repo):
    results = search_law.search_by_name(repo, "폐지된", None, 10, include_repealed=True)
    assert len(results) == 1
    assert results[0]["metadata"]["상태"] == "폐지"


def test_search_by_name_doc_type_대통령령(repo):
    """--doc-type 대통령령 필터가 대통령령.md를 찾아야 한다 (기존 버그)."""
    results = search_law.search_by_name(repo, "독립", "대통령령", 10)
    assert len(results) == 1
    assert results[0]["doc_type"] == "대통령령"


def test_search_exact_multiple_articles(repo):
    """--articles '제1조,제2조' 복수 조문 추출."""
    results = search_law.search_exact(repo, "테스트법률", None, "제1조,제2조")
    assert len(results) == 1
    articles = results[0]["articles"]
    assert "목적" in articles["제1조"]
    assert "정의" in articles["제2조"]


def test_search_exact_single_article(repo):
    results = search_law.search_exact(repo, "테스트법률", None, "제1조")
    assert "목적" in results[0]["articles"]["제1조"]


# ---------------------------------------------------------------------------
# git 이력 기능 (--history / --as-of)
# ---------------------------------------------------------------------------

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo, *args, date=None):
    env = dict(GIT_ENV)
    if date:
        env["GIT_AUTHOR_DATE"] = f"{date}T12:00:00 +0900"
        env["GIT_COMMITTER_DATE"] = f"{date}T12:00:00 +0900"
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


@pytest.fixture
def git_repo(tmp_path):
    repo = str(tmp_path)
    _git(repo, "init", "-q")
    law_dir = tmp_path / "kr" / "이력법률"
    law_dir.mkdir(parents=True)
    f = law_dir / "법률.md"
    f.write_text("---\n제목: 이력법률\n상태: 시행\n---\n\n##### 제1조(목적)\n최초 제정 조문.\n", encoding="utf-8")
    _git(repo, "add", "."); _git(repo, "commit", "-q", "-m", "법률: 이력법률 (제정)", date="2020-01-01")
    f.write_text("---\n제목: 이력법률\n상태: 시행\n---\n\n##### 제1조(목적)\n개정된 조문.\n", encoding="utf-8")
    _git(repo, "add", "."); _git(repo, "commit", "-q", "-m", "법률: 이력법률 (일부개정)", date="2023-05-05")
    return repo


def test_law_history(git_repo):
    history = search_law.law_history(git_repo, "이력법률")
    assert len(history) == 2
    assert history[0]["date"] == "2023-05-05"   # 최신순
    assert "일부개정" in history[0]["subject"]
    assert history[1]["date"] == "2020-01-01"


def test_law_content_as_of(git_repo):
    text = search_law.law_content_as_of(git_repo, "kr/이력법률/법률.md", "2022-01-01")
    assert "최초 제정 조문" in text
    assert "개정된 조문" not in text


def test_law_content_as_of_before_first_commit(git_repo):
    assert search_law.law_content_as_of(git_repo, "kr/이력법률/법률.md", "2019-01-01") is None
