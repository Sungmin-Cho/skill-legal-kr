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
    # 소관부처 (리스트)
    dept_matches = re.findall(r"^-\s+(.+)$", block, re.MULTILINE)
    if dept_matches:
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
    """파일명으로 법령 유형을 판별한다."""
    mapping = {
        "법률.md": "법률",
        "시행령.md": "시행령",
        "시행규칙.md": "시행규칙",
        "대통령령.md": "대통령령",
    }
    return mapping.get(filename, "기타")


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
    # 다음 조문 헤더까지 추출
    next_article = re.compile(r"^#{1,6}\s+제\d+")
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if next_article.match(lines[i]):
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


def search_by_name(repo_path: str, keyword: str, doc_type: str | None, limit: int) -> list:
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
            if meta.get("상태") == "폐지":
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


def search_by_keyword(repo_path: str, keyword: str, doc_type: str | None, limit: int, snippet: bool) -> list:
    """법령 본문에서 키워드를 검색한다."""
    kr_dir = Path(repo_path) / "kr"
    if not kr_dir.exists():
        return []
    # subprocess로 grep 호출 (빠른 파일 목록 확보)
    cmd = ["grep", "-rl", "--include=*.md", keyword, str(kr_dir)]
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
        if meta.get("상태") == "폐지":
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


def search_exact(repo_path: str, name: str, doc_type: str | None, articles: str | None, snippet_kw: str | None) -> list:
    """정확한 법령명으로 디렉토리에 직접 접근한다."""
    # 공백 제거 (legalize-kr 규칙)
    dir_name = name.replace(" ", "")
    kr_dir = Path(repo_path) / "kr" / dir_name
    if not kr_dir.exists():
        # 부분 매칭 시도
        parent = Path(repo_path) / "kr"
        candidates = [d for d in parent.iterdir() if d.is_dir() and dir_name in d.name]
        if not candidates:
            return []
        kr_dir = candidates[0]
    results = []
    for md_file in sorted(kr_dir.glob("*.md")):
        dt = detect_doc_type(md_file.name)
        if doc_type and dt != doc_type:
            continue
        text = md_file.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        entry = {
            "path": str(md_file.relative_to(repo_path)),
            "법령명": meta.get("제목", kr_dir.name),
            "doc_type": dt,
            "metadata": meta,
        }
        if articles:
            article_text = extract_article(text, articles)
            if article_text:
                entry["article"] = article_text
            else:
                entry["article"] = f"{articles}을(를) 찾을 수 없습니다."
        elif snippet_kw:
            entry["snippet"] = make_snippet(text, snippet_kw)
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
    parser.add_argument("--doc-type", choices=["법률", "시행령", "시행규칙", "대통령령"], help="법령 유형 필터")
    parser.add_argument("--articles", help="특정 조문 추출 (예: 제3조)")
    parser.add_argument("--snippet", action="store_true", help="키워드 주변 텍스트만 추출")
    parser.add_argument("--limit", type=int, default=10, help="결과 개수 제한 (기본: 10)")
    args = parser.parse_args()

    if args.name:
        results = search_by_name(args.repo, args.name, args.doc_type, args.limit)
    elif args.keyword:
        results = search_by_keyword(args.repo, args.keyword, args.doc_type, args.limit, args.snippet)
    elif args.exact:
        results = search_exact(args.repo, args.exact, args.doc_type, args.articles, args.keyword)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
