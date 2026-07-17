# AGENTS.md — legal-kr 공통 프로젝트 지침

> Codex와 Claude Code가 공유하는 프로젝트 지침의 단일 기준 문서입니다.
> 루트 `CLAUDE.md`는 이 파일을 `@AGENTS.md`로 가져옵니다.

## 프로젝트 개요

**legal-kr**은 대한민국 법령·판례의 로컬 원문을 검색하여 근거 기반 법률 분석을 제공하는 스킬 프로젝트입니다.

- 법령 데이터: `legalize-kr/` — 국가법령정보센터에서 수집한 법령과 Git 개정 이력
- 판례 데이터: `precedent-kr/` — 대법원·하급심 판례와 검색용 메타데이터
- 데이터 출처: [국가법령정보센터 OpenAPI](https://open.law.go.kr)
- 프로젝트 설명과 일반 사용법: `README.md`

## 에이전트별 스킬 경로

| 실행 환경 | 프로젝트 스킬 경로 | 프로젝트 설정 |
|-----------|--------------------|---------------|
| Codex | `.agents/skills/legal-kr/` | 루트 `AGENTS.md` |
| Claude Code | `.claude/skills/legal-kr/` | `.claude/settings.json` |

- `.Codex/`는 이 프로젝트에서 사용하는 경로가 아니다.
- 두 스킬 디렉터리는 런타임별 진입점일 뿐 같은 검색·상담 동작을 제공해야 한다.
- 스킬이나 검색 스크립트를 변경하면 양쪽 사본을 함께 반영하고 테스트한다.
- `CLAUDE.md`에는 중복 지침을 복사하지 않는다. Claude 전용 지침이 꼭 필요한 경우에만 `@AGENTS.md` 아래에 추가한다.

## 저장소 구조

```text
legal-kr/
├── AGENTS.md                         # 공통 프로젝트 지침(단일 기준)
├── CLAUDE.md                         # @AGENTS.md import
├── README.md
├── .agents/skills/legal-kr/          # Codex 스킬
├── .claude/
│   ├── settings.json
│   └── skills/legal-kr/              # Claude Code 스킬
├── tests/                            # 검색 스크립트 pytest
├── outputs/                          # 분석 결과물(git 추적 제외)
├── legalize-kr/                      # 법령 데이터(별도 clone)
│   └── kr/{법령명}/{문서유형}.md
└── precedent-kr/                     # 판례 데이터(별도 clone)
    ├── metadata.json
    ├── stats.json
    └── {사건종류}/{법원급}/{사건번호}.md
```

정확한 데이터 규모는 고정값을 신뢰하지 말고 다음 명령으로 확인한다.

```bash
ls legalize-kr/kr | wc -l
python3 -c 'import json; print(json.load(open("precedent-kr/stats.json")))'
```

## 작업 분류와 필수 스킬

### 법률 관련 요청

법률 상담, 법령 분석, 조문 해설, 판례 검색, 계약·분쟁 자문 등에는 반드시 현재 런타임의 `legal-kr` 스킬을 먼저 읽고 그 워크플로우를 따른다.

1. 데이터 상태와 분석 기준일을 확인한다.
2. 사실관계와 쟁점을 정리하고, 결론에 영향을 주는 정보가 부족하면 질문한다.
3. 로컬 법령 원문과 필요한 경우 해당 시점의 법령을 검색한다.
4. 관련 판례 원문을 검색한다.
5. 확인된 근거와 해석·의견을 구분하고, 유리한 근거와 불리한 근거를 함께 분석한다.
6. 조문 번호, 사건번호, 선고일자와 원문 경로 또는 출처 URL을 제시한다.
7. 아래 결과물 저장 규칙에 따라 출력한다.

일반 지식만으로 법률 결론을 내리지 않는다. 로컬 원문을 우선하고, 중요한 인용은 법령 파일의 `출처` URL로 원문을 재확인한다.

### 법률과 무관한 요청

프로젝트 관리, 문서 정리, 검색 스크립트 개발과 같은 비법률 작업에는 상담 워크플로우를 호출할 필요가 없다. 해당 파일과 테스트를 직접 확인한다.

## 데이터 조회 규칙

### 법령

- 경로: `legalize-kr/kr/{법령명(공백 제거)}/{문서유형}.md`
- 주요 문서유형: `법률.md`, `시행령.md`, `시행규칙.md`, `대통령령.md`, `대법원규칙.md`
- 법령명에는 `·`(U+00B7) 대신 `ㆍ`(U+318D) 정규화가 적용될 수 있다.
- YAML frontmatter의 `공포일자`, `시행일자`, `상태`, `출처`를 본문과 함께 확인한다.
- 사건 당시 법령이 쟁점이면 현행 조문만 보지 말고 `--as-of YYYY-MM-DD` 또는 해당 파일의 Git 이력을 사용한다.
- 1970-01-01 이전 법령은 Git 날짜가 1970-01-01일 수 있으므로 실제 `공포일자` 필드를 기준으로 한다.

### 판례

- 경로: `precedent-kr/{사건종류}/{법원급}/{사건번호}.md`
- 사건번호 직접 검색을 우선하고, 쟁점·참조조문·본문 키워드 검색으로 확장한다.
- 판시사항이나 판결요지만 떼어 결론을 과장하지 말고 필요한 범위에서 이유와 사실관계도 확인한다.

### 검색 명령

현재 런타임에 맞는 스킬 디렉터리를 선택한다.

```bash
# Codex
LEGAL_KR_SKILL_DIR=.agents/skills/legal-kr

# Claude Code에서는 위 값을 다음으로 바꾼다.
# LEGAL_KR_SKILL_DIR=.claude/skills/legal-kr

python3 "$LEGAL_KR_SKILL_DIR/scripts/search_law.py" --exact "민법" --articles "제750조"
python3 "$LEGAL_KR_SKILL_DIR/scripts/search_law.py" --exact "민법" --as-of 2020-06-01 --articles "제750조"
python3 "$LEGAL_KR_SKILL_DIR/scripts/search_precedent.py" --case "2024다268508"
```

데이터 저장소가 기본 위치에 없으면 스킬이 지원하는 `LEGALIZE_KR_PATH`, `PRECEDENT_KR_PATH` 또는 `--repo` 옵션을 사용한다.

## 결과물 저장 규칙

- 단순 조회(특정 조문 확인, 단건 판례 검색)는 대화 응답으로 충분하다. 사용자가 요청하면 저장한다.
- 상담형·분석형 요청은 반드시 `outputs/`에 저장하고 대화에 파일 링크를 제공한다.
- 기본 형식은 Markdown이다. 사용자가 형식을 명시한 경우에만 `.docx`, `.xlsx`, `.pptx`, `.pdf`를 사용한다.
- 파일명: `{법령명또는주제}_{작업유형}_{YYYYMMDD}.{확장자}`
- `outputs/`가 없으면 생성한다.

예시:

```text
outputs/민법_조문분석_20260717.md
outputs/근로기준법_요약보고서_20260717.docx
```

## 변경 및 검증 규칙

- 법령·판례 원문은 분석 대상 데이터다. 사용자가 명시적으로 요청하지 않는 한 내용을 수정하지 않는다.
- 검색 스크립트를 변경한 경우 양쪽 런타임 사본의 동작을 맞추고 다음 테스트를 실행한다.

```bash
python3 -m pytest tests/
```

- 데이터 저장소의 히스토리가 force-push로 재작성될 수 있으므로 작업 전 상태를 확인한다.
- `git reset --hard` 같은 파괴적 재동기화는 자동으로 실행하지 않는다. 필요한 경우 영향 범위를 설명하고 사용자 승인을 받은 뒤 진행한다.
- 관련 없는 사용자 변경사항은 보존한다.
