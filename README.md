# legal-kr

대한민국 법령(3,046개)과 판례(123,469건)를 검색하여 근거 기반 법률 조언을 제공하는 Claude Code 프로젝트 스킬.

## 개요

현재 상황을 설명하면, 실제 법령 조문과 대법원 판례를 인용하는 변호사 스타일의 법률 의견을 제공합니다.

**스킬 없이 Claude에게 물어볼 때:**
- 일반적인 법률 지식 기반 답변
- 구체적 조문 번호 누락 가능
- 판례 인용 불가

**스킬 적용 시:**
- 실제 법령 조문을 정확히 인용 (법률 + 시행령 + 시행규칙)
- 최신 대법원 판례를 표준 인용 형식으로 제시
- 법령 원문 출처 링크(law.go.kr) 포함
- 체계적 법률 의견서 형식 (쟁점 → 법령 → 판례 → 분석 → 조언)

## 데이터 소스

| 저장소 | 내용 | 규모 |
|--------|------|------|
| [legalize-kr](https://github.com/legalize-kr/legalize-kr) | 대한민국 법령 (법률, 시행령, 시행규칙, 대통령령) | 3,046개 법령, 6,907개 파일 |
| [precedent-kr](https://github.com/legalize-kr/precedent-kr) | 대한민국 판례 (대법원 + 하급심) | 123,469건 |

법령 데이터는 [국가법령정보센터 OpenAPI](https://open.law.go.kr)에서 수집된 공공저작물입니다.

## 설치

```bash
# 1. 저장소 클론
git clone https://github.com/Sungmin-Cho/skill-legal-kr.git
cd skill-legal-kr

# 2. 법령/판례 데이터 클론
git clone https://github.com/legalize-kr/legalize-kr.git
git clone https://github.com/legalize-kr/precedent-kr.git

# 3. Claude Code 실행
claude
```

스킬은 `.claude/skills/legal-kr/`에 있으며, 이 디렉토리에서 Claude Code를 실행하면 법률 관련 질문 시 자동으로 활성화됩니다.

## 사용 예시

### 개인 법률 상담

```
전세 계약이 만료됐는데 집주인이 보증금을 안 돌려줘요.
전입신고는 하고 살았고, 확정일자도 받았어요. 어떻게 해야 하나요?
```

→ 주택임대차보호법 제3조(대항력), 제3조의2(우선변제권) 인용 + 2025년 대법원 판례 + 내용증명→임차권등기명령→소송 절차 안내

### 법률 리서치

```
개인정보보호법에서 민감정보 처리 요건이 뭔지 상세하게 알려줘.
시행령이랑 시행규칙도 같이 확인해줘.
```

→ 법률 제23조 + 시행령 제18조 + 안전조치 기준을 통합 분석

### 노동법 상담

```
회사에서 갑자기 내일부터 안 나와도 된다고 통보받았습니다.
3년 넘게 다닌 정규직인데 부당해고 아닌가요?
```

→ 근로기준법 제23조(정당한 이유), 제26조(해고예고), 제27조(서면통지) + 부당해고 구제신청 절차

## 프로젝트 구조

```
legal-kr/
├── .claude/skills/legal-kr/       ← 변호사 스킬
│   ├── SKILL.md                   ← 스킬 정의 (워크플로우 6단계)
│   └── scripts/
│       ├── search_law.py          ← 법령 검색
│       └── search_precedent.py    ← 판례 검색
├── legalize-kr/                   ← 법령 데이터 (git submodule)
├── precedent-kr/                  ← 판례 데이터 (git submodule)
└── README.ko.md
```

## 검색 스크립트

### search_law.py — 법령 검색

```bash
# 법령명 키워드 검색
python3 .claude/skills/legal-kr/scripts/search_law.py --name "임대차" --doc-type 법률

# 정확한 법령명으로 직접 접근
python3 .claude/skills/legal-kr/scripts/search_law.py --exact "민법" --articles "제750조"

# 법령 본문 키워드 검색
python3 .claude/skills/legal-kr/scripts/search_law.py --keyword "보증금" --snippet --limit 10
```

주요 옵션:
- `--name` : 법령명에서 키워드 검색
- `--keyword` : 법령 본문에서 키워드 검색
- `--exact` : 정확한 법령명으로 직접 접근
- `--doc-type` : `법률`, `시행령`, `시행규칙`, `대통령령` 필터
- `--articles` : 특정 조문 추출 (조문 번호 또는 표제)
- `--snippet` : 키워드 주변 텍스트만 추출

### search_precedent.py — 판례 검색

```bash
# 사건명 키워드 검색 (빠름)
python3 .claude/skills/legal-kr/scripts/search_precedent.py --title "보증금" --court "대법원" --limit 10

# 참조조문 기반 검색 (특정 법령을 인용한 판례)
python3 .claude/skills/legal-kr/scripts/search_precedent.py --law "주택임대차보호법" --court "대법원" --content --limit 5

# 판례 본문 키워드 검색
python3 .claude/skills/legal-kr/scripts/search_precedent.py --text "부당해고" --type "민사" --snippet --limit 10
```

주요 옵션:
- `--title` : 사건명에서 키워드 검색 (metadata 기반, 빠름)
- `--text` : 판례 본문에서 키워드 검색
- `--law` : 참조조문에서 법령명 검색
- `--type` : 사건종류 필터 (`민사`, `형사`, `가사`, `세무`, `일반행정`, `특허`)
- `--court` : 법원급 필터 (`대법원`, `하급심`)
- `--content` : 판시사항 + 판결요지 포함
- `--snippet` : 키워드 주변 텍스트만 추출

## 데이터 업데이트

스킬 실행 시 자동으로 `git pull`을 수행하여 최신 법령/판례를 반영합니다. 수동 업데이트:

```bash
cd legalize-kr && git pull && cd ..
cd precedent-kr && git pull && cd ..
```

## 데이터 출처 및 인용 정보

### 법령 데이터 — legalize-kr

| 항목 | 내용 |
|------|------|
| 저장소 | [legalize-kr/legalize-kr](https://github.com/legalize-kr/legalize-kr) |
| 설명 | 대한민국 법령을 Git 저장소로 관리. 각 법령은 Markdown, 각 개정은 실제 공포일자를 가진 Git commit |
| 원본 데이터 | [국가법령정보센터 OpenAPI](https://open.law.go.kr) |
| 라이선스 | 법령 원문 — 공공저작물 (대한민국 정부 저작물), 저장소 구조/메타데이터 — MIT |
| 관련 프로젝트 | [legalize-kr/legalize-pipeline](https://github.com/legalize-kr/legalize-pipeline) (수집/변환 파이프라인), [legalize-kr/compiler](https://github.com/legalize-kr/compiler) (API→Git 컴파일러), [legalize-kr/legalize-web](https://github.com/legalize-kr/legalize-web) (웹사이트 [legalize.kr](https://legalize.kr)) |

### 판례 데이터 — precedent-kr

| 항목 | 내용 |
|------|------|
| 저장소 | [legalize-kr/precedent-kr](https://github.com/legalize-kr/precedent-kr) |
| 설명 | 대한민국 판례를 사건종류/법원급별로 분류한 Markdown 저장소 |
| 원본 데이터 | [국가법령정보센터 OpenAPI](https://open.law.go.kr) |
| 라이선스 | 판례 원문 — 공공저작물 (대한민국 정부 저작물) |
| 규모 | 대법원 68,002건, 하급심 55,466건 (민사 42,016 / 일반행정 45,028 / 형사 21,624 / 세무 10,024 / 특허 3,371 / 가사 1,387) |

> 두 저장소는 [legalize-kr](https://github.com/legalize-kr) 조직에서 운영하며,
> [legalize](https://github.com/legalize-dev/legalize) (스페인 법령 Git 프로젝트)에서 영감을 받았습니다.

## 면책 조항

이 스킬이 제공하는 정보는 AI 기반 참고용 법률 정보이며, 실제 법률 자문을 대체하지 않습니다.
정확한 법률 판단을 위해서는 변호사와 상담하시기 바랍니다.

## 라이선스

- 법령/판례 원문: 공공저작물 (대한민국 정부 저작물)
- 스킬 코드: MIT
