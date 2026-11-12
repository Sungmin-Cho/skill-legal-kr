#!/usr/bin/env python3
"""판례 검색 스크립트 — precedent-kr 저장소에서 판례를 검색한다."""

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_REPO = os.environ.get(
    "PRECEDENT_KR_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent.parent / "precedent-kr"),
)


INDEX_KEY = "__index__"  # 자동 생성 인덱스의 메타 정보 (판례 항목이 아님)
FRONTMATTER_KEYS = ("판례일련번호", "사건번호", "사건명", "법원명", "법원등급", "사건종류", "선고일자")


def git_head(repo_path: str) -> str | None:
    """저장소의 현재 git HEAD 커밋을 반환한다. git 저장소가 아니면 None."""
    try:
        proc = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def parse_frontmatter(filepath: Path) -> dict:
    """판례 파일의 YAML frontmatter에서 검색에 필요한 키만 읽는다 (표준 라이브러리만 사용)."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            if f.readline().strip() != "---":
                return {}
            data = {}
            for line in f:
                line = line.rstrip("\n")
                if line.strip() == "---":
                    break
                key, sep, value = line.partition(":")
                key = key.strip()
                if not sep or key not in FRONTMATTER_KEYS:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                data[key] = value
            return data
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return {}


def build_metadata(repo_path: str) -> dict:
    """판례 파일의 frontmatter를 읽어 metadata 인덱스를 만든다.
    반환 형식: {판례일련번호: {사건명, 사건번호, 선고일자, 법원명, 사건종류, path}}
    path는 저장소 기준 상대 경로이며 OS와 무관하게 '/'로 구분한다.
    """
    root = Path(repo_path)
    files = [fp for fp in root.glob("*/*/*.md") if ".git" not in fp.parts]
    # 파일 12만여 개를 여는 I/O가 대부분이므로 스레드로 병렬 처리한다.
    with ThreadPoolExecutor(max_workers=16) as pool:
        parsed = pool.map(parse_frontmatter, files, chunksize=256)
        pairs = list(zip(files, parsed))
    metadata = {}
    for fp, fm in pairs:
        if not fm:
            continue
        rel = fp.relative_to(root).as_posix()
        entry_id = fm.get("판례일련번호") or rel
        metadata[entry_id] = {
            "사건명": fm.get("사건명", ""),
            "사건번호": fm.get("사건번호", ""),
            "선고일자": fm.get("선고일자", ""),
            "법원명": fm.get("법원명", ""),
            "사건종류": fm.get("사건종류", "") or fp.parts[-3],
            "path": rel,
        }
    return metadata


def build_stats(metadata: dict) -> dict:
    """metadata 인덱스로 데이터 규모 통계를 만든다."""
    by_type, by_level = {}, {}
    for entry in metadata.values():
        parts = entry.get("path", "").split("/")
        by_type[entry.get("사건종류", "")] = by_type.get(entry.get("사건종류", ""), 0) + 1
        level = parts[1] if len(parts) > 2 else ""
        by_level[level] = by_level.get(level, 0) + 1
    return {"total": len(metadata), "사건종류": by_type, "법원등급": by_level}


def write_json(path: Path, data) -> None:
    """JSON 파일을 원자적으로 쓴다. 실패해도 검색은 계속한다."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        print(f"{path.name} 저장 실패(검색은 계속): {e}", file=sys.stderr)


def load_metadata(repo_path: str) -> dict:
    """metadata.json을 로딩한다.
    precedent-kr 저장소는 metadata.json·stats.json을 git으로 배포하지 않는다(.gitignore).
    파일이 없거나, 이 스크립트가 만든 인덱스가 현재 git HEAD와 다르면
    판례 frontmatter로 다시 만들어 저장한다. 직접 넣은 metadata.json(인덱스 정보 없음)은 그대로 쓴다.
    """
    meta_path = Path(repo_path) / "metadata.json"
    if not Path(repo_path).is_dir():
        print(f"precedent-kr 저장소를 찾을 수 없습니다: {repo_path}", file=sys.stderr)
        return {}
    head = git_head(repo_path)
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            index = data.pop(INDEX_KEY, None)
            if index is None or index.get("head") == head:
                return data
    print("metadata.json 인덱스를 판례 파일에서 생성합니다 (저장소 갱신 후 최초 1회, 수 분 소요)...",
          file=sys.stderr)
    metadata = build_metadata(repo_path)
    if not metadata:
        print(f"판례 파일을 찾지 못했습니다: {repo_path}", file=sys.stderr)
        return {}
    write_json(meta_path, {INDEX_KEY: {"head": head}, **metadata})
    write_json(Path(repo_path) / "stats.json", {**build_stats(metadata), "head": head})
    return metadata


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


def search_by_case(metadata: dict, case_no: str) -> list:
    """사건번호로 판례를 직접 조회한다.
    병합 사건('2024다227606, 227620')은 쉼표로 나뉜 개별 번호 각각으로 조회 가능하다.
    부분 일치는 지원하지 않는다 (번호 오매칭 방지).
    """
    query = case_no.strip()
    results = []
    for entry_id, entry in metadata.items():
        numbers = [n.strip() for n in entry.get("사건번호", "").split(",")]
        if query in numbers:
            results.append({**entry, "id": entry_id})
    return results


def relative_posix(fpath: str, repo_path: str) -> str | None:
    """grep 결과 경로를 metadata의 path 형식(저장소 기준, '/' 구분)으로 바꾼다."""
    try:
        return Path(fpath).resolve().relative_to(Path(repo_path).resolve()).as_posix()
    except ValueError:
        return None


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
        rel = relative_posix(fpath, repo_path)
        if rel is None:
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
        rel = relative_posix(fpath, repo_path)
        if rel is None:
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
    group.add_argument("--case", help="사건번호로 직접 조회 (예: 2024다268508)")

    parser.add_argument("--type", help="사건종류 필터 (민사, 형사, 가사, 세무, 일반행정, 특허, 기타, 선거·특별)")
    parser.add_argument("--court", help="법원급 필터 (대법원, 하급심)")
    parser.add_argument("--content", action="store_true", help="판시사항+판결요지 포함")
    parser.add_argument("--full", action="store_true", help="--case 조회 시 판례내용(전문)까지 포함")
    parser.add_argument("--snippet", action="store_true", help="키워드 주변 텍스트만 추출")
    parser.add_argument("--limit", type=int, default=10, help="결과 개수 제한 (기본: 10)")
    args = parser.parse_args()

    metadata = load_metadata(args.repo)
    if not metadata:
        print(json.dumps([], ensure_ascii=False))
        return

    if args.case:
        # 사건번호 직접 조회: 주요 섹션을 기본 포함하여 검색→Read 2단계를 줄인다
        sections = ["판시사항", "판결요지", "참조조문", "참조판례"]
        if args.full:
            sections.append("판례내용")
        output = []
        for entry in sort_results(search_by_case(metadata, args.case))[:args.limit]:
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
            item.update(extract_sections(str(Path(args.repo) / entry.get("path", "")), sections))
            output.append(item)
        print(json.dumps(output, ensure_ascii=False, indent=2))
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
