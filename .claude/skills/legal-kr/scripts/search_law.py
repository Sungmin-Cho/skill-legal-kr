#!/usr/bin/env python3
"""법령 검색 스크립트 — legalize-kr 저장소에서 법령을 검색한다."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# 저장소 기본 경로 (SKILL_DIR 기준 상대경로)
DEFAULT_REPO = os.environ.get(
    "LEGALIZE_KR_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent.parent / "legalize-kr"),
)


def parse_frontmatter(text: str) -> dict:
    """YAML frontmatter에서 필요한 키만 정규식으로 추출한다."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    meta = {}
    for key in ("제목", "상태", "공포일자", "출처", "법령구분", "법령MST"):
        match = re.search(rf"^{key}:\s*['\"]?(.+?)['\"]?\s*$", block, re.MULTILINE)
        if match:
            meta[key] = match.group(1).strip("'\"")
    # 소관부처 (리스트) — 들여쓰기된 항목("  - 법무부")이 실제 데이터 형식
    in_dept = False
    depts = []
    for line in block.splitlines():
        if line.startswith("소관부처:"):
            in_dept = True
            continue
        if in_dept:
            stripped = line.strip()
            if stripped.startswith("- "):
                depts.append(stripped[2:].strip())
            else:
                in_dept = False
    if depts:
        meta["소관부처"] = depts
    return meta


def detect_doc_type(filename: str) -> str:
    """파일명으로 법령 유형을 판별한다.
    법무부령.md, 시행규칙(총리령).md 등 변형 파일명도 올바르게 분류한다.
    """
    name = filename.removesuffix(".md")
    if name == "법률":
        return "법률"
    if name == "시행령":
        return "시행령"
    if "대통령령" in name:
        return "대통령령"
    if "시행규칙" in name or "규칙" in name or "부령" in name or "총리령" in name:
        return "시행규칙"
    return "기타"


def extract_article(text: str, article_num: str) -> str | None:
    """특정 조문을 추출한다.
    article_num은 '제750조' 같은 조문 번호 또는 '보증금의 회수' 같은 표제도 가능하다.
    legalize-kr의 일부 법령에서 '제3조의2'가 '제3조 (보증금의 회수)'로 표기되므로,
    표제 기반 검색도 지원한다.
    """
    escaped = re.escape(article_num)
    lines = text.split("\n")
    start_idx = None
    # 1차: 조문 번호 직접 매칭 (예: 제750조)
    pattern = re.compile(r"^#{1,6}\s+" + escaped + r"(?:\s|\()")
    for i, line in enumerate(lines):
        if pattern.match(line):
            start_idx = i
            break
    # 2차: 표제(제목) 매칭 (예: 보증금의 회수)
    if start_idx is None:
        for i, line in enumerate(lines):
            if re.match(r"^#{1,6}\s+제\d+", line) and article_num in line:
                start_idx = i
                break
    if start_idx is None:
        return None
    # 다음 조문 헤더 또는 부칙/별표까지 추출
    stop_pattern = re.compile(r"^#{1,6}\s+(제\d+|부칙|별표)")
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if stop_pattern.match(lines[i]):
            end_idx = i
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def make_snippet(text: str, keyword: str, context_lines: int = 3) -> str:
    """키워드 주변 전후 N줄을 추출한다."""
    lines = text.split("\n")
    result_lines = set()
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            for j in range(max(0, i - context_lines), min(len(lines), i + context_lines + 1)):
                result_lines.add(j)
    if not result_lines:
        return ""
    sorted_indices = sorted(result_lines)
    snippets = []
    for idx in sorted_indices:
        snippets.append(lines[idx])
    return "\n".join(snippets)


def search_by_name(repo_path: str, keyword: str, doc_type: str | None, limit: int,
                   include_repealed: bool = False) -> list:
    """법령명(디렉토리명)에서 키워드를 검색한다."""
    kr_dir = Path(repo_path) / "kr"
    if not kr_dir.exists():
        return []
    results = []
    for d in sorted(kr_dir.iterdir()):
        if not d.is_dir():
            continue
        if keyword.lower() not in d.name.lower():
            continue
        for md_file in sorted(d.glob("*.md")):
            dt = detect_doc_type(md_file.name)
            if doc_type and dt != doc_type:
                continue
            text = md_file.read_text(encoding="utf-8", errors="replace")
            meta = parse_frontmatter(text)
            if not include_repealed and meta.get("상태") == "폐지":
                continue
            results.append({
                "path": str(md_file.relative_to(repo_path)),
                "법령명": meta.get("제목", d.name),
                "doc_type": dt,
                "metadata": meta,
            })
            if len(results) >= limit:
                return results
    return results


def search_by_keyword(repo_path: str, keyword: str, doc_type: str | None, limit: int, snippet: bool,
                      include_repealed: bool = False) -> list:
    """법령 본문에서 키워드를 검색한다."""
    kr_dir = Path(repo_path) / "kr"
    if not kr_dir.exists():
        return []
    # subprocess로 grep 호출 (빠른 파일 목록 확보)
    cmd = ["grep", "-rlF", "--include=*.md", keyword, str(kr_dir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        matched_files = [f.strip() for f in proc.stdout.strip().split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        matched_files = []
    results = []
    for fpath in matched_files:
        fp = Path(fpath)
        dt = detect_doc_type(fp.name)
        if doc_type and dt != doc_type:
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        if not include_repealed and meta.get("상태") == "폐지":
            continue
        entry = {
            "path": str(fp.relative_to(repo_path)),
            "법령명": meta.get("제목", fp.parent.name),
            "doc_type": dt,
            "metadata": meta,
        }
        if snippet:
            entry["snippet"] = make_snippet(text, keyword)
        results.append(entry)
        if len(results) >= limit:
            break
    return results


def resolve_law_dir(repo_path: str, name: str) -> Path | None:
    """법령명으로 kr/ 아래 디렉토리를 찾는다 (공백 제거 + 부분 매칭)."""
    dir_name = name.replace(" ", "")
    kr_dir = Path(repo_path) / "kr" / dir_name
    if kr_dir.exists():
        return kr_dir
    parent = Path(repo_path) / "kr"
    if not parent.exists():
        return None
    candidates = [d for d in parent.iterdir() if d.is_dir() and dir_name in d.name]
    return candidates[0] if candidates else None


def _run_git(repo_path: str, *args: str) -> str | None:
    """git 명령을 실행하고 stdout을 반환한다 (실패 시 None)."""
    try:
        proc = subprocess.run(["git", "-C", repo_path, *args],
                              capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def law_history(repo_path: str, name: str) -> list:
    """법령 디렉토리의 개정 이력(커밋 로그)을 최신순으로 반환한다.
    커밋 날짜 = 공포일자. 단, 1970-01-01 이전 공포 법령은 커밋 날짜가
    1970-01-01로 고정되어 있으므로 실제 공포일자는 frontmatter를 참조해야 한다.
    """
    law_dir = resolve_law_dir(repo_path, name)
    rel = f"kr/{law_dir.name}" if law_dir else f"kr/{name.replace(' ', '')}"
    out = _run_git(repo_path, "log", "--date=format:%Y-%m-%d",
                   "--pretty=format:%H|%ad|%s", "--", rel)
    if not out:
        return []
    history = []
    for line in out.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            history.append({"hash": parts[0], "date": parts[1], "subject": parts[2]})
    return history


def law_content_as_of(repo_path: str, rel_file: str, date: str) -> str | None:
    """특정 날짜(공포일자 기준) 시점의 파일 내용을 반환한다.
    해당 날짜 이전 마지막 커밋의 버전을 가져오며, 없으면 None."""
    out = _run_git(repo_path, "log", "--before", f"{date}T23:59:59",
                   "-1", "--format=%H", "--", rel_file)
    if not out or not out.strip():
        return None
    return _run_git(repo_path, "show", f"{out.strip()}:{rel_file}")


def search_exact(repo_path: str, name: str, doc_type: str | None = None,
                 articles: str | None = None, as_of: str | None = None) -> list:
    """정확한 법령명으로 디렉토리에 직접 접근한다.

    articles: 쉼표로 구분한 복수 조문 지정 가능 (예: "제1조,제2조").
    as_of: YYYY-MM-DD — 해당 날짜(공포일자 기준) 시점의 조문을 git 이력에서 조회.
    """
    kr_dir = resolve_law_dir(repo_path, name)
    if kr_dir is None:
        return []
    results = []
    for md_file in sorted(kr_dir.glob("*.md")):
        dt = detect_doc_type(md_file.name)
        if doc_type and dt != doc_type:
            continue
        rel_path = str(md_file.relative_to(repo_path))
        if as_of:
            text = law_content_as_of(repo_path, rel_path, as_of)
            if text is None:
                continue  # 해당 시점에 존재하지 않던 문서
        else:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        entry = {
            "path": rel_path,
            "법령명": meta.get("제목", kr_dir.name),
            "doc_type": dt,
            "metadata": meta,
        }
        if as_of:
            entry["기준일"] = as_of
        if articles:
            found = {}
            for art in [a.strip() for a in articles.split(",") if a.strip()]:
                article_text = extract_article(text, art)
                found[art] = article_text if article_text else f"{art}을(를) 찾을 수 없습니다."
            entry["articles"] = found
        else:
            # frontmatter 이후 본문 (조문 목차 수준)
            body = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.DOTALL)
            # 헤딩 목록만 추출
            headings = [line for line in body.split("\n") if line.startswith("#")]
            entry["headings"] = headings[:50]
        results.append(entry)
    return results


def main():
    parser = argparse.ArgumentParser(description="법령 검색 (legalize-kr)")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="legalize-kr 저장소 경로")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", help="법령명에서 키워드 검색")
    group.add_argument("--keyword", help="법령 본문에서 키워드 검색")
    group.add_argument("--exact", help="정확한 법령명으로 직접 접근")
    parser.add_argument("--doc-type", choices=["법률", "시행령", "시행규칙", "대통령령", "기타"], help="법령 유형 필터")
    parser.add_argument("--articles", help="특정 조문 추출 — 쉼표로 복수 지정 가능 (예: 제3조 또는 제1조,제2조)")
    parser.add_argument("--snippet", action="store_true", help="키워드 주변 텍스트만 추출")
    parser.add_argument("--include-repealed", action="store_true", help="폐지된 법령도 결과에 포함")
    parser.add_argument("--history", action="store_true", help="법령 개정 이력(공포일자 커밋 로그) 출력 (--exact 전용)")
    parser.add_argument("--as-of", dest="as_of", metavar="YYYY-MM-DD",
                        help="해당 날짜(공포일자 기준) 시점의 조문 조회 (--exact 전용)")
    parser.add_argument("--limit", type=int, default=10, help="결과 개수 제한 (기본: 10)")
    args = parser.parse_args()

    if (args.history or args.as_of) and not args.exact:
        parser.error("--history/--as-of 옵션은 --exact와 함께 사용해야 합니다.")

    if args.name:
        results = search_by_name(args.repo, args.name, args.doc_type, args.limit,
                                 include_repealed=args.include_repealed)
    elif args.keyword:
        results = search_by_keyword(args.repo, args.keyword, args.doc_type, args.limit, args.snippet,
                                    include_repealed=args.include_repealed)
    elif args.exact:
        if args.history:
            results = law_history(args.repo, args.exact)
        else:
            results = search_exact(args.repo, args.exact, args.doc_type, args.articles, args.as_of)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
