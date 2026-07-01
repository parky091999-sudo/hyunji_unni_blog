"""
주식 블로그 원고 생성 (공모주·주식분석·ETF 카테고리).
수집된 데이터만 입력, Gemini로 네이버 블로그 포맷(마커) 출력.
"""
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta

from generator.content import _gen_text, _parse_response, _IMAGE_MARKER

logger = logging.getLogger("stock_content")

KST = timezone(timedelta(hours=9))

STOCK_TOPICS: dict[str, dict] = {
    "상한가특징주": {
        "name": "오늘의 상한가 & 특징주",
        "blog_category": "주식분석",
        "table_header": "종목명 | 현재가 | 등락률",
        "sec2": "오늘 장 마감 핵심 정리",
        "sec4": "투자자가 확인할 점",
    },
    "공모주캘린더": {
        "name": "공모주 캘린더",
        "blog_category": "공모주",
        "table_header": "종목명 | 공모가 | 청약일 | 상장일",
        "sec2": "이번 주 청약·상장 일정",
        "sec4": "청약 전 체크리스트",
    },
    "etf포트폴리오": {
        "name": "핵심 ETF 포트폴리오",
        "blog_category": "ETF",
        "table_header": "티커 | 현재가(USD) | 전일대비(%)",
        "sec2": "코어 ETF 한눈에 보기",
        "sec4": "포트폴리오 참고 포인트",
    },
}


def _today_str() -> str:
    return datetime.now(KST).strftime("%Y년 %m월 %d일")


def _build_stock_system(cfg: dict) -> str:
    return (
        "너는 금융 데이터를 분석하는 실사용자 지향형 전문 블로거 '현지언니'야.\n"
        "아래 [팩트 데이터]만을 바탕으로 네이버 블로그 포스팅용 원고를 작성해라.\n"
        "\n[대원칙 — 반드시 준수]\n"
        f"1. 기준 시점: {_today_str()}을 제목·서두에 명시\n"
        "2. 서두: '안녕하세요'·'반갑습니다'·'후기입니다' 등 인사말 절대 금지. 핵심 정보로 즉시 시작\n"
        "3. 문체: 해요체 또는 합니다체, 담백하고 자연스럽게(AI 티 금지)\n"
        "4. 이모지 절대 사용 금지\n"
        "5. 할루시네이션 방지: 제공된 수치 외 주가·원인·데이터를 절대 지어내지 마라\n"
        "6. 투자 권유 금지: '지금 사세요' 대신 '참고용 데이터' 톤 유지\n"
        "\n[글 구조 — 이 순서 그대로, 마커 필수]\n"
        "\n[사진1]\n(도입 2~3줄. 첫 문장에 날짜·핵심 수치. 인사말 금지.)\n"
        "\n[요약시작]\n"
        "· 핵심 1: (팩트 한 줄)\n"
        "· 핵심 2: (팩트 한 줄)\n"
        "· 핵심 3: (팩트 한 줄)\n"
        "[요약끝]\n"
        "\n[소제목] 한눈에 보는 핵심 데이터\n"
        "(1~2문장 요약 후 아래 표)\n"
        f"[표시작]\n{cfg['table_header']}\n"
        "(팩트 데이터를 표 행으로 채워라. 빈칸 금지. 제공 데이터에 없는 행 추가 금지)\n"
        "[표끝]\n"
        f"\n[소제목] {cfg['sec2']}\n"
        "(팩트 기반 설명 2~3문장. 불릿 3~4줄, 각 줄 '· '로 시작)\n"
        "· (팩트1)\n· (팩트2)\n· (팩트3)\n"
        "\n[소제목] 꼭 알아둘 점\n"
        "(투자 유의사항. 불릿 3줄, '· '로 시작)\n"
        "· (유의1)\n· (유의2)\n· (유의3)\n"
        f"\n[소제목] {cfg['sec4']}\n"
        "(단계 ①②③, 각 1줄)\n"
        "① ~\n② ~\n③ ~\n"
        "\n[소제목] 자주 묻는 질문\n"
        "[FAQ시작]\n"
        "Q: (질문1)\nA: (답변 — 팩트 범위 내)\n"
        "Q: (질문2)\nA: (답변)\n"
        "Q: (질문3)\nA: (답변)\n"
        "[FAQ끝]\n"
        "\n(마무리 1~2줄. 투자 판단은 본인 책임, 공식 자료·증권사 앱으로 재확인 권장. "
        "쿠팡 리뷰·도움이 돼요 버튼 문구 절대 금지)\n"
        "\n[출력 형식]\n"
        "TITLE: {제목 — 날짜·핵심 키워드, 35자 이내}\n"
        "TAGS: {태그6~8개, 쉼표 구분}\n"
        "IMAGE_KEYWORDS: stock header\n"
        "IMAGE_LABELS: {소분류명}\n"
        "---\n{본문}\n"
        "\n[마커 체크리스트]\n"
        "- [사진1] 1개만. [사진2]+ 금지\n"
        "- [요약시작]~[요약끝] 1쌍\n"
        "- [표시작]~[표끝] 1쌍 (3~4열, 팩트만)\n"
        "- [FAQ시작]~[FAQ끝] 1쌍\n"
        "- [소제목] 5개\n"
        "- 마무리: 면책·공식 확인 권장만 (공감/리뷰 CTA 금지)\n"
    )


def generate_stock_post(topic_id: str, fact_data: dict | list, api_key: str) -> dict | None:
    """팩트 데이터 기반 주식 인사이트 포스트 생성."""
    cfg = STOCK_TOPICS.get(topic_id)
    if not cfg:
        logger.error(f"알 수 없는 주식 소분류: {topic_id}")
        return None

    system = _build_stock_system(cfg)
    facts_json = json.dumps(fact_data, ensure_ascii=False, indent=2)
    category_hint = ""
    if cfg.get("blog_category") == "주식분석":
        category_hint = (
            "네이버 카테고리 '주식분석' — 당일 상한가·특징주 팩트 요약이지만, "
            "개별 종목 심층 분석 글과 같은 맥락의 데이터 정리 톤으로 작성.\n"
        )

    user_msg = (
        f"소분류: {cfg['name']}\n"
        f"네이버 블로그 카테고리: {cfg.get('blog_category', '')}\n"
        f"기준일: {_today_str()}\n"
        f"{category_hint}\n"
        f"[팩트 데이터 — 이 데이터만 사용, 추가·변조 금지]\n{facts_json}\n\n"
        "위 팩트만으로 네이버 블로그 원고를 작성해라. "
        "표 행은 제공된 데이터 항목만 채워라. 데이터가 5건 이하면 전부 표에 넣어라."
    )

    waits = [15, 40, 90]
    for attempt in range(1, len(waits) + 2):
        try:
            raw = _gen_text(api_key, user_msg, system, 8192, 0.15)
            if not raw:
                logger.error(f"{cfg['name']} 빈 응답 (시도 {attempt})")
                continue
            parsed = _parse_response(raw)
            if not parsed:
                logger.warning(f"{cfg['name']} 파싱 실패 (시도 {attempt})")
                continue

            body_len = len(_IMAGE_MARKER.sub("", parsed.get("body", "")))
            if body_len < 600:
                logger.warning(f"{cfg['name']} 본문 짧음 ({body_len}자) — 재생성")
                continue

            body = parsed.get("body", "")
            body = re.sub(
                r"\n*이 리뷰가 마음에 들었으면 도움이 돼요 버튼을 눌러주세요\s*",
                "\n",
                body,
            )
            parsed["body"] = body.rstrip()

            if not parsed.get("table_strs"):
                logger.warning(f"{cfg['name']} 표 누락 — 재생성")
                continue

            logger.info(
                f"{cfg['name']} 생성 완료: {parsed.get('title')!r} "
                f"(본문 {body_len}자, 표={bool(parsed.get('table_strs'))})"
            )
            parsed["stock_topic"] = topic_id
            parsed["fact_data"] = fact_data
            return parsed

        except Exception as e:
            logger.error(f"{cfg['name']} 생성 실패 (시도 {attempt}): {e}")
            if attempt <= len(waits):
                time.sleep(waits[attempt - 1])
    return None
