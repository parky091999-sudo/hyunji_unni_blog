"""
Gemini 2.5 Flash로 네이버 블로그 글 생성
출력: {title, tags, body, coupang_hints}
body는 plain text (단락 구분 \n\n) — Playwright 타이핑용
"""
import logging
import re
import time

from google import genai
from google.genai import types as gtypes

logger = logging.getLogger(__name__)

_SYSTEM = """\
당신은 네이버 블로그 전문 작가입니다.
페르소나: 20대 후반 신혼주부 "현지언니" — 살림 꿀팁을 친근하게 공유
글 스타일: 까꿍언니 같은 톤 (친근, 유쾌, 실용적, 직접 써본 것처럼)
주제: 1인 가구 / 신혼 살림 / 생활 꿀팁 / 집 정리 / 생활비 절약

작성 규칙:
1. 제목: 핵심 키워드 포함, 클릭하고 싶은 제목 (20~35자), "~하는 법" "~꿀팁" "~추천" 형식
2. 본문: 일반 텍스트 (HTML 태그 금지), 2000~3000자
   - 소제목은 【소제목】 형식으로 표시
   - 항목 나열은 ✔ 기호 사용
   - 이모지 자유롭게 사용
   - 쿠팡 추천 상품 위치: [쿠팡추천1] [쿠팡추천2] 플레이스홀더
   - 마무리: "다음에는 ~도 알려드릴게요 😊" 스타일
3. 태그: 5~8개 (SEO 핵심 키워드, 쉼표 구분)
4. 쿠팡 힌트: 본문에 자연스럽게 추천할 상품 키워드 2개

출력 형식 (정확히 지켜줘):
TITLE: {제목}
TAGS: {태그1},{태그2},...
COUPANG_HINT_1: {쿠팡 검색 키워드 1}
COUPANG_HINT_2: {쿠팡 검색 키워드 2}
---
{본문 (plain text)}
"""


def _parse_response(raw: str) -> dict | None:
    try:
        lines = raw.strip().splitlines()
        result: dict = {"coupang_hints": []}
        body_start = None

        for i, line in enumerate(lines):
            if line.startswith("TITLE:"):
                result["title"] = line[6:].strip()
            elif line.startswith("TAGS:"):
                result["tags"] = [t.strip() for t in line[5:].split(",") if t.strip()]
            elif line.startswith("COUPANG_HINT_"):
                result["coupang_hints"].append(re.sub(r"^COUPANG_HINT_\d+:\s*", "", line).strip())
            elif line.strip() == "---":
                body_start = i + 1
                break

        if body_start is None:
            # --- 없으면 빈 줄 두 개 이후를 본문으로
            for i, line in enumerate(lines):
                if line.strip() == "" and i > 3:
                    body_start = i + 1
                    break

        if body_start is not None:
            # [쿠팡추천N] 플레이스홀더 제거
            body = "\n".join(lines[body_start:]).strip()
            body = re.sub(r"\[쿠팡추천\d+\]", "", body)
            result["body"] = body

        if "title" not in result or "body" not in result:
            logger.warning("파싱 실패")
            return None

        result.setdefault("tags", [])
        return result
    except Exception as e:
        logger.error(f"파싱 오류: {e}")
        return None


def generate_post(keyword: str, api_key: str, trending: list[str] | None = None) -> dict | None:
    """
    keyword: 오늘 포스팅 키워드
    반환: {title, tags, body, coupang_hints}
    """
    trend_note = ""
    if trending:
        trend_note = f"\n참고 트렌딩 (자연스럽게 연결되면 살짝 언급): {', '.join(trending[:4])}"

    user_msg = f"오늘 포스팅 키워드: {keyword}{trend_note}\n\n위 주제로 블로그 글을 작성해줘."

    # 503/500 transient 에러 대비 지수 백오프 재시도
    waits = [15, 40, 90, 180]  # 시도 간 대기(초): 15 → 40 → 90 → 180
    client = genai.Client(api_key=api_key)
    for attempt in range(1, len(waits) + 2):  # 최대 5회
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_msg,
                config=gtypes.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    max_output_tokens=4000,
                    temperature=0.85,
                ),
            )
            raw = (resp.text or "").strip()
            if not raw:
                logger.error(f"Gemini 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if parsed:
                logger.info(f"글 생성 완료: {parsed.get('title')!r} ({len(parsed.get('body',''))}자)")
                return parsed
        except Exception as e:
            logger.error(f"Gemini 생성 실패 (시도 {attempt}/{len(waits)+1}): {e}")
            if attempt <= len(waits):
                wait = waits[attempt - 1]
                logger.info(f"{wait}초 후 재시도...")
                time.sleep(wait)
    return None
