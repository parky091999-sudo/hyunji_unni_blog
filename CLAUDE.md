# naver_blog 프로젝트 컨텍스트

## 프로젝트 개요
네이버 블로그 생활꿀팁 자동 포스팅 파이프라인
GitHub Actions 매일 KST 10:00 실행 (Playwright 브라우저 자동화)

**블로그:** blog.naver.com/hyunji_unni
**네이버 계정 ID:** hyunji_unni
**블로그명/닉네임:** 현지언니
**주제:** 신혼/1인 가구 살림 꿀팁, 생활비 절약, 집 정리
**페르소나:** 20대 후반 신혼주부 "현지언니" (친근한 까꿍언니 스타일)
**수익 구조:** 쿠팡 파트너스 (글 내 링크, 추후 자동화) + 애드포스트 (3개월 후 신청)

---

## 포스팅 방식
- Naver Blog API 폐지됨 → Playwright로 SE3 에디터 직접 조작
- 쿠키 기반 세션 재사용 (get_cookies.py로 1회 발급 → GitHub Secret에 저장)

---

## 핵심 파일 구조

```
generator/
  keyword.py      — 에버그린 키워드 + 시즌 키워드 풀
  content.py      — Gemini 2.5 Flash 블로그 글 생성 (plain text)
  image.py        — Pexels API 이미지 (추후 활용)
poster/
  naver_blog.py   — Playwright SE3 에디터 자동 포스팅
scripts/
  daily_post.py   — 메인 실행 (매일 1회)
  get_cookies.py  — 초기 쿠키 발급 (로컬 1회 실행, headless=False)
data/
  post_history.json    — 포스팅 이력 (중복 방지)
  naver_cookies.json   — 로컬 쿠키 저장 (GH Actions는 Secret 사용)
.github/workflows/
  daily_post.yml  — GitHub Actions 스케줄러
```

---

## GitHub Secrets 필요 목록

| Secret | 설명 |
|---|---|
| `NAVER_ID` | hyunji_unni |
| `NAVER_PW` | 네이버 비밀번호 |
| `NAVER_COOKIES` | get_cookies.py 실행 후 출력되는 JSON (쿠키 만료 시 재발급) |
| `GOOGLE_API_KEY` | Gemini API 키 |
| `PEXELS_API_KEY` | Pexels 이미지 API 키 (없어도 동작) |

---

## 초기 셋업 순서

1. .env 파일 생성 (NAVER_ID, NAVER_PW, GOOGLE_API_KEY 입력)
2. `pip install -r requirements.txt && playwright install chromium`
3. `python scripts/get_cookies.py` 실행 → 브라우저에서 로그인 → 쿠키 저장
4. data/naver_cookies.json 내용 전체를 GitHub Secret `NAVER_COOKIES`에 등록
5. 나머지 Secrets 등록 (NAVER_ID, NAVER_PW, GOOGLE_API_KEY)
6. GitHub Actions 활성화

---

## 알려진 설계 결정

- 중복 방지: data/post_history.json 날짜 기준 (당일 1회)
- 쿠키 만료: 약 30~90일 → get_cookies.py 재실행 후 Secret 업데이트
- 이미지: 1단계는 텍스트 위주 포스팅, 추후 이미지 삽입 자동화 추가 예정
- 쿠팡 링크: coupang_hints 로깅만 (추후 자동 링크 삽입 추가 예정)
