# 작업 인수인계 — 2026-07-06 마감 → 다음 세션 (다른 PC 이어작업용)

> **다른 PC에서 시작할 때 이 파일부터 읽으세요.** 상세 기술 로그는 [docs/WRITING_SYSTEM.md](docs/WRITING_SYSTEM.md) §7.
> ※이 파일은 07-05 버전을 07-06 세션(장시간, 커밋 15개+)으로 전면 갱신한 것.

---

## 0. 프로젝트 요약

- **현지언니 네이버 블로그**(blog.naver.com/hyunji_unni) 자동 포스팅 파이프라인. Playwright로 SE ONE 에디터 조작, GH Actions 크론.
- 활성: 정부지원(09시)·정보성 4종(금융/세금/보험/부동산, 13·15·17·19시 순환)·주식 3종(종목분석 16:30/공모주 09시/ETF 07시).
- 원칙: 실데이터만, 모바일 가독성, 두괄식+FAQ, 중립·정확.

---

## ★ 2026-07-06 밤 추가 세션 (전부 push됨, main af00667) — 벤치마킹 비주얼 대개편 + 워드프레스 착수

### A. 두번째스물하나(ggonnip100) 벤치마킹 — 본문 비주얼 3종 (상세 §7)
- **개념 카드 인포그래픽**([사진3]): 요약 불릿→'핵심 N가지' 번호배지 카드, 카테고리 색상 자동. info(4종)+gov 배선·DRAFT 검증.
- **에디토리얼 AI 일러스트**([사진2]): Imagen 4.0 Fast 주제맞춤 플랫벡터(강한 스타일 제약으로 드리프트 방지). gov/info가 버린 '무관 스톡사진' 문제 해결. DRAFT images_inserted=3 검증.
- 배치=`generator/body_layout.arrange_body_image_markers`(헤더[사진1]+일러스트[사진2]+개념[사진3]). **정기 크론 실발행부터 모든 정보성·정부지원 글에 자동 적용.**
- ⑤신청주석 스크린샷·②컬러소제목은 **자동발행 안전/SEO상 보류**(근거 §7). ④마스코트=일러스트로 충족.

### B. 워드프레스 확장 착수 (9월 수익화 목표)
- **`generator/wp_render.py`**: 네이버 마커 본문→시맨틱 HTML+SEO(meta·slug·Article/FAQPage 스키마). 실제 생성글 검증 완료. **아직 호출부 없음**(네이버 라이브 무영향).
- 방향 확정: 자가호스팅 WordPress.org(주말 가입 예정) + REST API 발행. 콘텐츠 재활용, poster만 교체. ⚠️네이버판과 중복 회피 변형 레이어 필요.
- 사용자: 티스토리+애드센스 이미 승인. 실업급여 9월까지라 **애드센스 연결은 9월 마지막 수령 후**. GitHub Actions는 계속 사용(실행 엔진).
- 🔜 주말: 형님이 호스팅 가입 → 사이트URL·관리자ID·Application Password 받아 `poster/wp_publish.py` 발행 어댑터 연결.

### C. 오늘 결과확인 중 발견·수정
- 중첩 마크다운 불릿(`    *   `) 라이브 노출 버그 수정(정규식 `^\s*` 완화). 도시가스 번호·공모주 실천팁은 수정前 런이라 예상됨(다음 런 자동해결).

---

## 1. 오늘(7/6) 낮 완료한 일 (전부 push됨)

### A. 어제(7/5) 벤치마킹 작업 실발행 종합검증 + 누락 보완
- sector_compare ETF 실발행(224337686714): 후킹제목·공감도입·비교인포그래픽·요약✓ 정상 확인. **출처인용·실천팁이 sector_compare 템플릿에 누락**됐던 것 발견·수정(17bd1f1).
- info/gov 후킹제목 DRAFT 검증, 종목분석에도 실천팁 확대(5e74219).

### B. 신기능: 네이버금융 공식 차트
- finance.naver.com 차트가 **정적 PNG로 직접 서빙**됨을 발견(`ssl.pstatic.net/imgfinance/chart/item/area/day/{code}.png`, 로그인 불필요) → Playwright 캡처 없이 requests로 다운로드.
- 국내 종목분석([사진3], 7667be8) + 국내 상장 ETF 개별분석(2943d0a)에 적용. 삼성전자 실발행(224337852825)·진흥기업/RISE DRAFT 검증.

### C. 버그 근본해결 2건 (사용자 실물 발견)
- **이미지 삽입 위치 오류**(삼성전자 글 문장 두 동강): DRAFT 6회 실측 끝에 확정 — 시도·기각 3종(ArrowDown 보정루프/JS selection/page.mouse 좌표클릭 전부 SE ONE과 어긋남). **채택: 원래 클릭 로직 복원 + Escape·중앙스크롤 완화 + 콘텐츠 레벨 해결**(지시문 에코 금지 _COMMON_RULES 12번 + '위 [은는]' 조사 복구)(e4334d0). ★교훈 "SE ONE 3대 불변": 내부캐럿은 실제 클릭·키입력으로만 / DOM 조작(텍스트·selection)은 발행본에 무효 / 합성 보정기계는 원래 로직보다 위험 — §7 기록.
- **도시가스 글 번호 중복**("2. 2."): 모델이 아라비아 "1. " 출력 시 SE 오토포맷이 리스트 자동생성 → `_parse_response`에서 ①~⑳ 정규화(ebfda3e, 전 파이프라인 공통). 라이브 깨진 글 2개(삼성전자·도시가스)는 사용자 결정으로 방치.

### D. 보험 카테고리 집중 보완 (카테고리 품질 검토 결과 최약체)
- **검토 근거**: 6개 글=사실상 3개 주제(국민연금 2연속·자동차보험 2연속), 팩트 소스 0, 라이브 글에 무근거 수치·비교 데이터 부재·공식도구 미언급.
- **🔴전 카테고리 공통 키워드 중복 버그 수정**(607fd14): 30일 회피가 살림용 post_history.json만 읽음 + DataLab 트렌딩이 재선정마다 같은 키워드 반환. → `pick_keyword_for_blog_category(exclude=)` 신설, info/gov 배선.
- 보험 키워드 풀 20→44(국민연금 제거), FSS finlife 연금저축 공시 배선(연금 키워드만, 기존 FSS_API_KEY), 템플릿 강화(sec4='공식 비교 도구로 직접 확인하는 법': 보험다모아·네이버페이/토스 비교·내보험찾아줌 / 무근거 수치 금지 / 특정사 추천 금지 중립). 벤치마킹: 토스피드·뱅크샐러드. DRAFT 검증: 장마철 '차량 침수' 키워드 자동선정+요약블록 신규 항목 확인.
- **잔여 갭 2종 추가**(809b4b8): 주제 클러스터 3일 쿨다운(`TOPIC_CLUSTERS` 보험 7클러스터 — 키워드 달라도 같은 계열 연속 방지) + 무근거 인용 하드 게이트(`_UNSOURCED_RE` "알려져 있"류 → 재생성, 전 정보성 공통).
- 라이브 중복 2쌍(국민연금 7/4·7/5, 주택청약 7/3·7/5)은 **사용자 결정으로 방치**(유사문서 리스크 인지).

### E. (별도 repo) 유진 jiniee_pipeline
- 팔로워 100 돌파 → 인사이트 조회 체계 구축(`scripts/check_user_insights.py` + `insights.yml` 수동 워크플로). 7일 views 27,192(7/3부터 급증 — 저녁 21시 논쟁·질문형이 견인, replies 224개 글이 6,482뷰).
- **대댓봇 Gemini 복구**(aed6733): 구 SDK import로 항상 실패→Groq 쿼터 소진 병목이었음. 신 SDK 교체, dry-run 검증.

---

## 2. 다음 세션 할 일 (우선순위)

### 🥇 1순위 — 오늘 수정분 결과 확인 (작업 없이 확인만)
```
# ①스모크 DRAFT(28778192666) ✅확인 완료: '암 진단비 얼마가 적당' 선정(클러스터 정상 통과),
#   후킹제목, 무근거 게이트 재생성 없음, DRAFT_SAVED 1,584자 — 크래시 0.
# ②내일 크론 실발행 훑기(라이브 글 직접 열기):
#  - 이미지 위치 정상(문장 분할 0)? 번호 리스트 정상("2. 2." 없음)?
#  - 보험 글: '공식 비교 도구로 직접 확인하는 법' 섹션 실물? 무근거 수치 없음?
#  - 공모주 글: '오늘 바로 확인해볼 것' 실천팁 첫 실발행?
#  - 국내 종목분석/국내 ETF: 네이버금융 공식 차트 정위치?
```

### 🥈 2순위 — 유진 후속 (지시 대기 항목)
- 대댓봇 백로그 소화 확인(4h 크론, replied.json 증가 추이).
- **주제 가중치 개편**(제안 승인 대기): 저녁 논쟁·질문형 확대, 점심 슬롯 재검토 — 인사이트 데이터 근거는 memory/jiniee CLAUDE.md 참고.
- 주간 인사이트 자동 리포트(크론+텔레그램) — **텔레그램 봇 토큰 미설정**이라 사용자 선행 필요.

### 🥉 3순위 — 오래 이월된 항목
- 구버전 라이브 글 일괄 비공개(살림 시절 등) — 자동화 미구축.
- FSS 연금저축 팩트 라이브 검증(보험 '연금' 키워드 걸릴 때 로그 확인).
- 색상/음영 강조: SE ONE 자동화 불가로 보류 확정(§7).

---

## 3. 다른 PC에서 시작하는 법

1. `git clone https://github.com/parky091999-sudo/hyunji_unni_blog.git` (또는 `git pull`). 유진은 `jiniee_pipeline.git`.
2. `.env`는 git에 없음 — 실발행·검증은 전부 GH Actions(Secrets)로 하므로 로컬 .env 없이도 workflow_dispatch로 작업 가능. `gh auth login` 필요.
3. 검증 명령 패턴:
   - DRAFT(비공개): `gh workflow run info_post.yml -f category=보험 -f draft=true -f force_post=true`
   - 주식: `gh workflow run stock_post.yml -f stock_topic=종목분석 -f draft=true -f force_post=true`
   - 결과: `gh run list` → `gh run view <ID> --log` + `gh run download <ID>`(스크린샷)
   - 라이브 글 확인: 네이버 블로그 URL은 WebFetch 차단 → 로컬 Playwright(`pw.chromium.launch(channel="chrome")`, 본문은 PostView iframe). scripts/_probe_live_post.py 참고(이 파일은 이전 PC에만 있는 untracked 로컬 도구 — 새로 만들면 됨, ~30줄).
4. **글쓰기/프롬프트 작업 전 [docs/WRITING_SYSTEM.md](docs/WRITING_SYSTEM.md) §5·§6·§7 필독** (CLAUDE.md 규칙).
5. push 전 `git pull --rebase --autostash origin main` (크론이 이력 커밋을 수시로 푸시함) → push 후 `git rev-list --left-right --count origin/main...HEAD`로 0/0 확인.
