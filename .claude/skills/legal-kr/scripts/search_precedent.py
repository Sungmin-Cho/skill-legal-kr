#!/usr/bin/env python3
"""판례 검색 스크립트 — precedent-kr 저장소에서 판례를 검색한다."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = os.environ.get(
    "PRECEDENT_KR_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent.parent / "precedent-kr"),
)


def load_metadata(repo_path: str) -> dict:
    """metadata.json을 로딩한다."""
    meta_path = Path(repo_path) / "metadata.json"
    if not meta_path.exists():
        print(f"metadata.json not found: {meta_path}", file=sys.stderr)
        return {}
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def make_citation(entry: dict) -> str:
    """표준 법률 인용 형식을 생성한다.
    형식: '대법원 2023. 1. 1. 선고 2022다12345 판결'
    """
    court = entry.get("법원명", "")
    date_str = entry.get("선고일자", "")
    case_num = entry.get("사건번호", "")
    if date_str and len(date_str) >= 10:
        # YYYY-MM-DD → YYYY. M. D.
        parts = date_str.split("-")
        if len(parts) == 3:
            y, m, d = parts
            formatted_date = f"{y}. {int(m)}. {int(d)}."
        else:
            formatted_date = date_str
    else:
        formatted_date = date_str
    return f"{court} {formatted_date} 선고 {case_num} 판결"


def extract_sections(filepath: str, sections: list[str] | None = None) -> dict:
    """판례 파일에서 특정 섹션을 추출한다."""
    if sections is None:
        sections = ["판시사항", "판결요지", "참조조문"]
    try:
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, PermissionError):
        return {}
    result = {}
    for section in sections:
        pattern = rf"^## {section}\s*\n(.*?)(?=^## |\Z)"
        m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if m:
            result[section] = m.group(1).strip()
    return result


def make_snippet_from_text(text: str, keyword: str, context_chars: int = 300) -> str:
    """키워드 주변 텍스트를 추출한다."""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return ""
    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(keyword) + context_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def match_court(entry: dict, court_filter: str | None) -> bool:
    """법원급 필터를 매칭한다.
    '대법원' → 법원명이 정확히 '대법원'인 경우
    '하급심' → path가 '하급심/' 디렉토리에 있거나 법원명이 '대법원'이 아닌 경우
    기타 → 법원명 직접 비교 (예: '서울고등법원')
    """
    if not court_filter:
        return True
    court_name = entry.get("법원명", "")
    if court_filter == "대법원":
        return court_name == "대법원"
    if court_filter == "하급심":
        path = entry.get("path", "")
        return "하급심/" in path or court_name != "대법원"
    return court_filter in court_name


def search_by_title(metadata: dict, keyword: str, case_type: str | None, court: str | None) -> list:
    """사건명(metadata)에서 키워드를 검색한다."""
    results = []
    for entry_id, entry in metadata.items():
        name = entry.get("사건명", "")
        if keyword.lower() not in name.lower():
            continue
        if case_type and entry.get("사건종류", "") != case_type:
            continue
        if not match_court(entry, court):
            continue
        results.append({**entry, "id": entry_id})
    return results


def search_by_text(repo_path: str, metadata: dict, keyword: str,
                   case_type: str | None, court: str | None) -> list:
    """판례 본문(판시사항+판결요지+참조조문)에서 키워드를 검색한다."""
    # 사건종류 필터로 검색 범위 축소
    search_dir = str(Path(repo_path))
    if case_type:
        candidate = Path(repo_path) / case_type
        if candidate.exists():
            search_dir = str(candidate)
    if court:
        candidate = Path(search_dir) / court
        if candidate.exists():
            search_dir = str(candidate)

    cmd = ["grep", "-rlF", "--include=*.md", keyword, search_dir]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        matched_files = [f.strip() for f in proc.stdout.strip().split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        matched_files = []

    # metadata와 조인
    path_to_id = {}
    for entry_id, entry in metadata.items():
        path_to_id[entry.get("path", "")] = (entry_id, entry)

    results = []
    for fpath in matched_files:
        fp = Path(fpath)
        try:
            rel = str(fp.relative_to(repo_path))
        except ValueError:
            continue
        if rel in path_to_id:
            entry_id, entry = path_to_id[rel]
            if not match_court(entry, court):
                continue
            results.append({**entry, "id": entry_id})
    return results


def search_by_law(repo_path: str, metadata: dict, law_name: str,
                  case_type: str | None, court: str | None) -> list:
    """판례 본문의 참조조문 섹션에서 법령명을 검색한다."""
    # 참조조문 섹션이 있는 파일만 대상
    search_dir = str(Path(repo_path))
    if case_type:
        candidate = Path(repo_path) / case_type
        if candidate.exists():
            search_dir = str(candidate)

    cmd = ["grep", "-rlF", "--include=*.md", law_name, search_dir]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        matched_files = [f.strip() for f in proc.stdout.strip().split("\n") if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        matched_files = []

    path_to_id = {}
    for entry_id, entry in metadata.items():
        path_to_id[entry.get("path", "")] = (entry_id, entry)

    results = []
    for fpath in matched_files:
        fp = Path(fpath)
        try:
            rel = str(fp.relative_to(repo_path))
        except ValueError:
            continue
        if rel not in path_to_id:
            continue
        entry_id, entry = path_to_id[rel]
        if not match_court(entry, court):
            continue
        # 참조조문 섹션에 법령명이 있는지 확인
        sections = extract_sections(fpath, ["참조조문"])
        ref = sections.get("참조조문", "")
        if law_name in ref:
            results.append({**entry, "id": entry_id, "matched_section": "참조조문", "참조조문": ref})
    return results


def sort_results(results: list) -> list:
    """대법원 우선 → 선고일자 내림차순 정렬."""
    def sort_key(entry):
        court_priority = 0 if entry.get("법원명") == "대법원" else 1
        date = entry.get("선고일자", "0000-00-00")
        # 단기 연도(4xxx) 처리 — 실제로는 오래된 판례
        if date.startswith("4"):
            date = "1" + date[1:]
        # 날짜를 역전하여 내림차순 정렬 (court_priority 오름 + date 내림)
        inverted_date = "".join(chr(ord("9") - ord(c)) if c.isdigit() else c for c in date)
        return (court_priority, inverted_date)

    return sorted(results, key=sort_key)


def format_results(results: list, repo_path: str, content: bool, snippet_kw: str | None, limit: int) -> list:
    """결과를 JSON 출력 형식으로 포맷한다."""
    if len(results) > 50:
        print(f"경고: 검색 결과가 {len(results)}건입니다. 검색어를 세분화해주세요.", file=sys.stderr)

    sorted_results = sort_results(results)[:limit]
    output = []
    for entry in sorted_results:
        item = {
            "id": entry.get("id", ""),
            "사건명": entry.get("사건명", ""),
            "사건번호": entry.get("사건번호", ""),
            "선고일자": entry.get("선고일자", ""),
            "법원명": entry.get("법원명", ""),
            "사건종류": entry.get("사건종류", ""),
            "citation": make_citation(entry),
            "path": entry.get("path", ""),
        }
        if entry.get("matched_section"):
            item["matched_section"] = entry["matched_section"]
        if entry.get("참조조문"):
            item["참조조문"] = entry["참조조문"]

        if content or snippet_kw:
            filepath = str(Path(repo_path) / entry.get("path", ""))
            if content:
                sections = extract_sections(filepath, ["판시사항", "판결요지"])
                item.update(sections)
            if snippet_kw:
                try:
                    text = Path(filepath).read_text(encoding="utf-8", errors="replace")
                    item["snippet"] = make_snippet_from_text(text, snippet_kw)
                except (FileNotFoundError, PermissionError):
                    pass
        output.append(item)
    return output


def main():
    parser = argparse.ArgumentParser(description="판례 검색 (precedent-kr)")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="precedent-kr 저장소 경로")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--title", help="사건명에서 키워드 검색 (metadata 기반, 빠름)")
    group.add_argument("--text", help="판례 본문에서 키워드 검색 (grep 기반)")
    group.add_argument("--law", help="참조조문에서 법령명 검색")

    parser.add_argument("--type", help="사건종류 필터 (민사, 형사, 가사, 세무, 일반행정, 특허)")
    parser.add_argument("--court", help="법원급 필터 (대법원, 하급심)")
    parser.add_argument("--content", action="store_true", help="판시사항+판결요지 포함")
    parser.add_argument("--snippet", action="store_true", help="키워드 주변 텍스트만 추출")
    parser.add_argument("--limit", type=int, default=10, help="결과 개수 제한 (기본: 10)")
    args = parser.parse_args()

    metadata = load_metadata(args.repo)
    if not metadata:
        print(json.dumps([]), ensure_ascii=False)
        return

    if args.title:
        results = search_by_title(metadata, args.title, args.type, args.court)
        snippet_kw = args.title if args.snippet else None
    elif args.text:
        results = search_by_text(args.repo, metadata, args.text, args.type, args.court)
        snippet_kw = args.text if args.snippet else None
    elif args.law:
        results = search_by_law(args.repo, metadata, args.law, args.type, args.court)
        snippet_kw = args.law if args.snippet else None
    else:
        results = []
        snippet_kw = None

    output = format_results(results, args.repo, args.content, snippet_kw, args.limit)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
