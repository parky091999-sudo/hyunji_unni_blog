# 작업 인수인계 — 2026-07-05 마감 → 내일 이어서

> **다른 PC에서 시작할 때 이 파일부터 읽으세요.** 오늘 한 일 / 왜 했는지 / 내일 할 일 / 시작 방법이 다 있습니다.
> 상세 기술 로그는 [docs/WRITING_SYSTEM.md](docs/WRITING_SYSTEM.md) §7(작업 로그)를 참고.

---

## 0. 이 프로젝트가 뭐고, 왜 하는지

- **현지언니 네이버 블로그**(blog.naver.com/hyunji_unni) **자동 포스팅 파이프라인**.
- **목표**: 검색 유입 기반으로 블로그를 키워 **네이버 애드포스트 → 티스토리+애드센스** 수익화.
- **주제**: ①고CPC 정보성(정부지원·금융·세금·보험·부동산) ②주식/ETF/공모주.
- **방식**: Playwright로 네이버 SE3 에디터를 자동 조작해 발행. GitHub Actions 크론으로 매일 자동.
- **핵심 원칙**: 실데이터만 사용(할루시네이션 금지), 모바일 가독성, 두괄식+FAQ(SEO), 중립·정확(현지언니 페르소나).

---

## 1. 오늘(7/5) 왜 이걸 했나 — 배경

**대형 블로거 2곳을 벤치마킹**해서 우리 약점을 보완하는 게 오늘의 큰 줄기였다.
- **너부리(주식경제노트)**: 데이터·일정·타임리 콘텐츠. AI인용 59.7만.
- **월부(월급쟁이부자들)**: 스토리텔링·설득·시각화. 이웃 5.2만.
- **우리 약점**: 밋밋한 표, 종목마다 똑같은 획일 구조, 낚시 없이 밋밋한 제목, 건조한 도입.
- (참고) 우리 블로그 통계도 봤음: 6월말 시작해 **일 66~76 조회로 우상향**, 검색 유입 44%, 롱테일 구체 키워드로 유입. **통계 기반 최적화는 2~3개월 뒤**(자리잡은 후)에 하기로 하고, 지금은 **대형 블로그 벤치마킹 위주**로 운영하기로 결정.

---

## 2. 오늘 완료한 일 (전부 커밋·푸시됨, origin/main)

### A. 구조·품질 (오전)
1. **ETF 유형별 구조 분화** — QLD(레버리지)에 배당 섹션이 억지로 붙던 문제 해결. 유형(배당/성장/레버리지/채권)별로 소제목·강조점을 완전히 다르게. 레버리지=원리/변동성/조합전략, 채권=금리민감도/방어역할 등.
2. **심화지표 수집** — 베타·연율변동성·S&P500상관·구성종목Top10·배당 재투자 백테스트.
3. **인라인 볼드 폐지** — `[[강조]]`가 한글+볼드토글 경계에서 글자 중복 오타("영향을 미 미치므로") 유발 → 폐지. 볼드는 소제목·표만.
4. **한글 끝글자 유실 완화** — 타이핑 후 조합 확정(End 키).
5. **가독성 후처리 전 카테고리 확대** — 덩어리 문단 자동 분리(`content._split_long_paragraphs`).

### B. 벤치마킹 반영 (오후)
6. **검색바 목업** (너부리) — 헤더카드에 "현지언니 [카테고리] 🔍검색".
7. **출처 명시** (너부리) — 표 다음 "· 출처: 야후파이낸스/네이버금융".
8. **FAQ 다양화** — 종목마다 똑같던 고정 3종 질문 → 종목 특성 반영.
9. **요약블록 ✓ 통일** — 카테고리마다 마커 제각각(✓/·)+"· ✓" 중복+끝"·" 오류 → 전부 "✓ "로 통일.
10. **비교 인포그래픽** (월부) ⭐ — 섹터비교 ETF의 밋밋한 표를 **디자인 비교 카드**로. 항목별 최적값 자동 초록강조. `infographic_html.create_comparison_infographic`. sector_compare에 [사진2]로 삽입.
11. **후킹 제목 + 공감 도입** (월부) — 제목에 결론약속/궁금증/리스트(과장·낚시 금지, 연도 필수). 도입 첫 문장 공감 후 즉시 두괄식.
12. **실천 팁 섹션** (월부) — ETF "오늘 바로 확인해볼 것"(투자권유 아닌 정보 확인 행동).

### 검증 상태
- 유형별구조: TQQQ/QQQ/VOO **실발행 검증됨**.
- 후킹제목·공감도입·실천팁: **DRY_RUN 검증**.
- 비교인포그래픽: **로컬 렌더 + DRAFT 앵커 삽입 검증**.
- 요약 ✓통일: **DRAFT 검증**.

---

## 3. 보류·미해결 (중요)

- **소제목 색상 / 형광펜 = 자동화 불가 (보류)**: SE ONE color-picker 팔레트는 실제 마우스 제스처가 필요해서 합성 클릭(locator/force/JS `el.click()`) 전부 실패. "표 열삭제 자동화 불가"와 같은 부류. **소제목은 볼드+버티컬라인으로 구분(색상 없음)**. 함수(`_apply_subheading_color`)·팔레트 실측값은 보존, 호출만 제거. 상세: WRITING_SYSTEM §7 미해결.

---

## 4. 내일 할 일 (우선순위 순)

### 🥇 1순위 — [검증] 공개 발행 1건 종합 검증
오늘 워낙 많이 바꿔서, **후킹제목+공감도입+실천팁+비교인포그래픽+요약✓통일+출처**가 실제 공개 발행에서 한 번에 다 정상인지 확인이 안 됐다.
```
gh workflow run stock_post.yml -f stock_topic=etf포트폴리오 -f etf_content_type=sector_compare_us -f force_post=true
# 완료 후 발행본(blog.naver.com/hyunji_unni 최신글) 열어서:
#  - 비교 인포그래픽이 [사진2]에 잘 들어갔나
#  - 요약블록이 전부 "✓ "로 통일됐나 (· ✓ 중복 없나)
#  - 제목이 후킹형인가, 도입이 공감→결론인가
#  - 출처·실천팁 섹션 있나
#  - 마커 노출([[)·글자유실 없나
```

### 🥈 2순위 — [남은 벤치마킹] 네이버 금융 실시간 캡쳐
너부리처럼 **국내 종목분석 글에 네이버 금융 실제 시세/차트 캡쳐**를 넣어 신뢰도↑.
- 어려운 점: 이미지 마커([사진N]) 재배치, 네이버 레이아웃 의존, 미국 ETF는 미지원(국내 종목분석만).
- 셀렉터 실측됨: 네이버 금융 종목페이지 `.new_totalinfo`(시세요약)·`.chart_area`(차트). `finance.naver.com/item/main.naver?code=XXX`.
- 접근: `generator/`에 캡쳐 함수(Playwright sync) 신설 → stock_post 종목분석 국내에서 생성 → images 추가 + 프롬프트 [사진N] 앵커.

### 🥉 3순위 (선택)
- info/gov 후킹 제목 실발행 확인(프롬프트만 바꿈, stock은 검증됨).
- 종목분석에도 실천 팁·후킹 강화 확대.

---

## 5. 다른 PC에서 시작하는 법

1. **저장소 받기**: `git clone https://github.com/parky091999-sudo/hyunji_unni_blog.git` (또는 기존 클론이면 `git pull origin main`).
2. **⚠️ `.env` 별도 준비** — `.env`는 git에 없음(비밀). 필요한 키: `NAVER_ID`, `NAVER_PW`, `NAVER_BLOG_ID`, `NAVER_COOKIES`, `GOOGLE_API_KEY`, `NAVER_CLIENT_ID/SECRET`, `FSS_API_KEY`. `.env.example` 참고. (실발행은 GitHub Actions Secrets로 돌아가니, 로컬은 DRY_RUN·생성 테스트용으로만 .env 필요.)
3. **의존성**: `pip install -r requirements.txt && playwright install chromium`.
4. **이 문서 + WRITING_SYSTEM.md §7** 읽으면 맥락 파악 끝.
5. **바로 1순위(공개 발행 검증)부터** 하면 됨 — 위 4번 명령.

### 로컬 생성 테스트 팁
- ETF 생성 DRY_RUN: `DRY_RUN=true STOCK_TOPIC=etf포트폴리오 python -m scripts.stock_post`
- info: `DRY_RUN=true python -m scripts.info_post`
- ⚠️ 로컬 yfinance가 SSL 인증서 오류나면(한글 경로 문제) 인증서를 ASCII 경로에 복사 후 `CURL_CA_BUNDLE`·`SSL_CERT_FILE` 지정. (이 PC에선 `C:/temp_probe/cacert.pem` 썼음. 새 PC는 경로 다를 수 있음.)
- **실발행은 최소화** — 블로그에 테스트글 쌓임. 검증은 `-f draft=true`(임시저장, 비공개) 활용.

---

## 6. 자주 쓰는 명령 요약

| 목적 | 명령 |
|---|---|
| 공개 발행(검증) | `gh workflow run stock_post.yml -f stock_topic=etf포트폴리오 -f etf_content_type=sector_compare_us -f force_post=true` |
| 임시저장 검증(비공개) | 위에서 `force_post=true` → `draft=true` |
| 발행 결과 로그 | `gh run list --limit 3` → `gh run view <ID> --log` |
| 최근 작업 맥락 | `docs/WRITING_SYSTEM.md` §7 (Resolved / Open) |
