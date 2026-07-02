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
    },
    "공모주캘린더": {
        "name": "공모주 캘린더",
        "blog_category": "공모주",
        "table_header": "종목명 | 공모가 | 청약일 | 상장일 | 경쟁률",
    },
    "etf포트폴리오": {
        "name": "핵심 ETF 포트폴리오",
        "blog_category": "ETF",
        "table_header": "티커 | 현재가(USD) | 전일대비(%) | 배당수익률(%) | 총보수(%)",
    },
}


def _today_str() -> str:
    return datetime.now(KST).strftime("%Y년 %m월 %d일")


_COMMON_RULES = (
    "너는 돈·투자 정보를 직접 발품 팔아 쉽게 정리해주는 생활정보 블로거 '현지언니'야.\n"
    "검색해서 들어온 사람이 '얻어갈 게 있다'고 느끼게, 숫자를 나열하지 말고 '그래서 이게 무슨 의미인지'를 해석해라.\n"
    "\n[대원칙 — 반드시 준수]\n"
    "1. 서두: '안녕하세요'·'반갑습니다'·'후기입니다' 등 인사말 절대 금지. 첫 문장은 날짜+핵심 결론으로 즉시 시작(두괄식)\n"
    "2. 문체: 해요체, 담백하고 자연스럽게(AI 상투어·'다양한'·'~하시길 바랍니다' 금지)\n"
    "3. 이모지 절대 사용 금지\n"
    "4. ★수치 할루시네이션 절대 금지: 특정 종목의 주가·등락률·경쟁률·배당률·보수·공모가 등 '구체 수치'는 "
    "[팩트 데이터]에 있는 값만 사용. 데이터에 없으면 '공시 미확정' 등으로 처리하고 절대 지어내지 마라.\n"
    "5. ★단, 제도·원리·투자 상식(균등/비례 배정 방식, 커버드콜 원리, 오버행·의무보유확약 개념, 레버리지 복리감소 등)은 "
    "일반 교육 지식으로 자유롭게 서술해도 된다. 이게 독자가 얻어가는 핵심 가치다.\n"
    "6. 투자 권유 금지: '지금 사세요' 대신 판단 기준을 제공하는 톤. 마지막은 '투자 책임은 본인, 공식 자료 재확인' 면책.\n"
    "7. 모든 소제목 바로 다음 1~2문장은 그 소제목 주제의 결론/정의를 즉시 답하는 두괄식으로.\n"
)

_OUTPUT_FORMAT = (
    "\n[출력 형식 — 반드시 이 형식]\n"
    "TITLE: {제목 — 날짜+핵심 키워드, 35자 이내, 클릭 유도하되 낚시 금지}\n"
    "TAGS: {태그 6~8개, 쉼표 구분}\n"
    "IMAGE_KEYWORDS: stock header\n"
    "IMAGE_LABELS: {소분류명}\n"
    "---\n{본문}\n"
)


def _struct_etf(cfg: dict) -> str:
    return (
        "\n[글 구조 — 이 순서, 마커 필수]\n"
        "\n[사진1]\n(도입 2~3줄. 첫 문장에 날짜와 오늘 4종목 등락 요약. 인사말 금지.)\n"
        "\n[요약시작]\n"
        "· 오늘 등락: (가장 오르내린 종목 중심 한 줄)\n"
        "· 배당 코어 vs 인컴 vs 레버리지 성격 차이 한 줄\n"
        "· 투자 전 꼭 볼 포인트 한 줄(환율·세금 등)\n"
        "[요약끝]\n"
        "\n[소제목] 오늘 코어 ETF 시세 한눈에\n"
        "(1~2문장 해석 후 표. 표엔 배당률·총보수까지 넣어 성격 차이가 보이게)\n"
        f"[표시작]\n{cfg['table_header']}\n"
        "(팩트 데이터의 티커별 값만. 없는 수치 칸은 '-'. 없는 행 추가 금지)\n[표끝]\n"
        "\n[소제목] 네 ETF, 성격이 이렇게 다릅니다\n"
        "(각 티커를 한 문단씩: 전략 성격(팩트 데이터의 '성격'·'전략'·'지급주기' 활용)을 쉽게 풀어라. "
        "SCHD=안정 배당코어, JEPQ=고배당 월인컴이지만 강세장 상단 제한, QLD/TQQQ=레버리지라 장기보유 시 복리감소 위험. "
        "불릿 '· '로 티커별 1~2줄.)\n"
        "\n[소제목] 배당률·보수 숫자, 이렇게 읽으세요\n"
        "(고배당의 함정을 해석: JEPQ류 두 자릿수 배당은 커버드콜 구조상 주가 상승분을 반납한 결과라 총수익은 다를 수 있음. "
        "총보수 0.06% vs 0.35% 차이가 장기 복리에 주는 영향. 불릿 3줄.)\n"
        "\n[소제목] 목적별 조합 예시 (참고용)\n"
        "(교육용 예시임을 명시. 안정형/인컴형/공격형으로 나눠 코어-위성 비중 예시. "
        "'정답이 아니라 예시'라고 못박고 ①②③로.)\n"
        "① 안정형: ~\n② 인컴형: ~\n③ 공격형: ~\n"
        "\n[소제목] 미국 ETF 투자 전 체크포인트\n"
        "(실전 주의: 분배금엔 미국 원천징수 15%, 환율 변동 영향, 월분배는 매달 금액 변동, 레버리지는 단기·소액. 불릿 3~4줄.)\n"
        "\n[소제목] 자주 묻는 질문\n"
        "[FAQ시작]\n"
        "Q: (SCHD랑 JEPQ 뭐가 다른가요 같은 실질 질문)\nA: (팩트+상식 범위)\n"
        "Q: (TQQQ 장기투자 괜찮나요 류)\nA: (복리감소 상식으로)\n"
        "Q: (세금·환율 류)\nA: (원천징수 15% 등)\n"
        "[FAQ끝]\n"
        "\n(마무리 1~2줄: 수치는 시점따라 변하니 각 운용사 공식 팩트시트 재확인, 투자 책임은 본인.)\n"
    )


def _struct_ipo(cfg: dict) -> str:
    return (
        "\n[글 구조 — 이 순서, 마커 필수]\n"
        "\n[사진1]\n(도입 2~3줄. 첫 문장에 날짜와 이번 주 청약/상장 종목 수·핵심 일정. 인사말 금지.)\n"
        "\n[요약시작]\n"
        "· 이번 주 청약: (임박한 종목·청약일 한 줄)\n"
        "· 이번 주 상장: (상장 예정 종목 한 줄)\n"
        "· 청약 판단 핵심: 경쟁률과 의무보유확약을 같이 본다 한 줄\n"
        "[요약끝]\n"
        "\n[소제목] 이번 청약·상장 일정 한눈에\n"
        "(1~2문장 후 표)\n"
        f"[표시작]\n{cfg['table_header']}\n"
        "(팩트 데이터 종목만. 미확정 칸은 '미정'. 없는 종목 추가 금지)\n[표끝]\n"
        "\n[소제목] 종목별 일정 코멘트\n"
        "(각 종목을 팩트(공모가·청약일·상장일·경쟁률·주간사)만으로 한 줄씩. 청약 마감 임박/증권사 어디인지 등 실용 정보. 불릿 '· '.)\n"
        "\n[소제목] 청약 전 꼭 볼 4가지\n"
        "(교육 프레임. ①수요예측 경쟁률은 의무보유확약 비율과 '함께' 봐야 오버행 판단 가능 "
        "②유통가능물량(오버행) 많으면 상장일 매물폭탄 위험 ③확정 공모가가 희망밴드 상단인지 하단인지 "
        "④균등배정(운)과 비례배정(자금) 차이. 각 2~3줄로 쉽게.)\n"
        "\n[소제목] 균등배정·증거금 계산법\n"
        "(교육: 균등배정은 최소 청약수량만 넣어도 추첨, 증거금=공모가×50%×청약주수. "
        "팩트 데이터에 '10주청약증거금'이 있으면 그 값을 예시로 인용. 중복청약 금지도 언급.)\n"
        "\n[소제목] 상장일 매도 전략 (참고용)\n"
        "(교육: 따상 확률은 통계적으로 낮고 오전 9시30분~10시 고점 패턴이 잦아 분할매도가 기본. "
        "오버행·공모가 부담 크면 보수적으로. '정답 아닌 참고'라고 명시. 불릿 3줄.)\n"
        "\n[소제목] 자주 묻는 질문\n"
        "[FAQ시작]\n"
        "Q: (경쟁률 높으면 무조건 오르나요 류)\nA: (확약·오버행 같이 봐야)\n"
        "Q: (균등이랑 비례 뭐가 유리한가요)\nA: (소액=균등)\n"
        "Q: (증거금 언제 환불되나요)\nA: (영업일 기준 안내)\n"
        "[FAQ끝]\n"
        "\n(마무리 1~2줄: 청약 전 증권신고서·수요예측 결과 공식 확인, 투자 책임은 본인.)\n"
    )


def _struct_upper(cfg: dict) -> str:
    return (
        "\n[글 구조 — 이 순서, 마커 필수]\n"
        "\n[사진1]\n(도입 2~3줄. 첫 문장에 날짜와 오늘 상한가 종목 수. 인사말 금지.)\n"
        "\n[요약시작]\n"
        "· 오늘 상한가: (종목 수·대표 종목 한 줄)\n"
        "· 상한가 종목을 볼 때 핵심: 왜 올랐는지·거래대금·연속성 한 줄\n"
        "· 추격매수 주의 한 줄\n"
        "[요약끝]\n"
        "\n[소제목] 오늘 상한가 종목\n"
        "(1~2문장 후 표. 팩트만)\n"
        f"[표시작]\n{cfg['table_header']}\n"
        "(팩트 데이터 종목만. 없는 종목·이유 추가 금지)\n[표끝]\n"
        "\n[소제목] 종목 훑어보기\n"
        "(팩트 데이터에 '재료'/'뉴스' 정보가 있으면 그것만 근거로 종목별 한 줄. "
        "없으면 상승 이유를 절대 추정하지 말고 '개별 재료는 공시·뉴스로 확인 필요'라고만. 불릿 '· '.)\n"
        "\n[소제목] 상한가 종목, 이렇게 판단하세요\n"
        "(교육 프레임: ①거래대금이 실려야 신뢰도 높음 ②연속 상한가인지 첫 상한가인지 ③테마가 지속성 있는지 "
        "단발성 뉴스인지. 각 2~3줄로.)\n"
        "\n[소제목] 뇌동매매 주의\n"
        "(교육: 상한가 다음날 변동성이 크고 추격매수는 고점 물릴 위험. 상한가는 '왜'를 모르면 진입 금물. 불릿 3줄.)\n"
        "\n[소제목] 관심종목 관리법\n"
        "(교육: 상한가 종목은 매수보다 '관찰 리스트'에 넣고 재료 지속·수급 확인 후 판단. ①②③ 각 1줄.)\n"
        "\n[소제목] 자주 묻는 질문\n"
        "[FAQ시작]\n"
        "Q: (상한가 종목 지금 사도 되나요 류)\nA: (왜 올랐는지 모르면 주의)\n"
        "Q: (상한가 다음날 어떻게 되나요)\nA: (변동성 큼, 통계적 주의)\n"
        "Q: (거래대금 왜 중요한가요)\nA: (수급 신뢰도)\n"
        "[FAQ끝]\n"
        "\n(마무리 1~2줄: 개별 종목 매매는 공시·뉴스 확인 후 본인 판단, 투자 책임은 본인.)\n"
    )


_STRUCT_BUILDERS = {
    "etf포트폴리오": _struct_etf,
    "공모주캘린더": _struct_ipo,
    "상한가특징주": _struct_upper,
}

_CHECKLIST = {
    "etf포트폴리오": "- [소제목] 6개(시세/성격/숫자읽기/조합/체크포인트/FAQ)\n",
    "공모주캘린더": "- [소제목] 6개(일정/코멘트/체크4/증거금/매도전략/FAQ)\n",
    "상한가특징주": "- [소제목] 6개(상한가종목/훑어보기/판단/뇌동매매/관심종목/FAQ)\n",
}


def _build_stock_system(topic_id: str, cfg: dict) -> str:
    struct_fn = _STRUCT_BUILDERS.get(topic_id, _struct_etf)
    checklist = _CHECKLIST.get(topic_id, "- [소제목] 6개\n")
    return (
        _COMMON_RULES
        + f"\n[기준 시점] {_today_str()} — 제목·서두에 명시\n"
        + struct_fn(cfg)
        + _OUTPUT_FORMAT
        + "\n[마커 체크리스트 — 누락 시 재작성]\n"
        "- [사진1] 1개만. [사진2]+ 금지\n"
        "- [요약시작]~[요약끝] 1쌍\n"
        "- [표시작]~[표끝] 1쌍 (팩트만)\n"
        "- [FAQ시작]~[FAQ끝] 1쌍\n"
        + checklist
        + "- 구체 수치는 팩트 데이터 값만, 제도·원리 설명은 교육으로 풍부하게\n"
        "- 마무리: 면책·공식 확인 권장만 (공감/리뷰 CTA 금지)\n"
    )


def generate_stock_post(topic_id: str, fact_data: dict | list, api_key: str) -> dict | None:
    """팩트 데이터 기반 주식 인사이트 포스트 생성."""
    cfg = STOCK_TOPICS.get(topic_id)
    if not cfg:
        logger.error(f"알 수 없는 주식 소분류: {topic_id}")
        return None

    system = _build_stock_system(topic_id, cfg)
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
