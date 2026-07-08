"""카테고리별 공식 출처 참조 — 네이버·WP 프롬프트 팩트 주입용."""

# info_cat_id → (기관명, 확인 URL)
INFO_OFFICIAL_SOURCES: dict[str, list[tuple[str, str]]] = {
    "금융재테크": [
        ("금융감독원 금융상품한눈에", "https://finlife.fss.or.kr"),
        ("국세청 연금·금융소득 안내", "https://www.nts.go.kr"),
        ("금융감독원 통합연금포털", "https://100lifeplan.fss.or.kr"),
    ],
    "세금절세": [
        ("국세청 홈택스", "https://www.hometax.go.kr"),
        ("국세청 연말정산·공제 안내", "https://www.nts.go.kr"),
    ],
    "보험": [
        ("보험다모아(생·손보협회)", "https://www.e-insmarket.or.kr"),
        ("내보험찾아줌", "https://cont.insure.or.kr"),
        ("금융감독원 FINE", "https://fine.fss.or.kr"),
    ],
    "부동산주거": [
        ("마이홈(국토교통부)", "https://www.myhome.go.kr"),
        ("주택도시기금", "https://nhuf.molit.go.kr"),
        ("국토교통부 실거래가", "https://rt.molit.go.kr"),
    ],
}

GOV_OFFICIAL_SOURCES: list[tuple[str, str]] = [
    ("복지로(정부24)", "https://www.bokjiro.go.kr"),
    ("국민신문고", "https://www.epeople.go.kr"),
    ("고용24", "https://www.work24.go.kr"),
]


def format_sources_block(sources: list[tuple[str, str]], header: str = "◆ 공식 확인 경로") -> str:
    if not sources:
        return ""
    lines = [header]
    for name, url in sources:
        lines.append(f"  · {name}: {url}")
    return "\n".join(lines) + "\n"
