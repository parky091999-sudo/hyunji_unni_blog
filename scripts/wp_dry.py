"""
워드프레스 심층분석 DRY_RUN — 발행 없이 생성→렌더→HTML 아티팩트만 (WP_PIPELINE §5 A단계).
GH Actions에서 GOOGLE_API_KEY로 실제 생성 품질을 검증한다. 로컬은 키가 없어 불가.

실행: WP_TOPIC=isa python -m scripts.wp_dry
결과: data/screenshots/wp_dry_<slug>.html (아티팩트 업로드) — 브라우저로 품질·렌더 검토
"""
import logging
import os
import sys

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config import GOOGLE_API_KEY, DATA_DIR
from generator.deep_content import generate_deep_post
from generator.wp_render import render_wordpress_post

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("wp_dry")

# 프로토타입 팩트 블록 — 프로덕션에선 constants_2026.yml + 데이터 수집기가 채운다.
TOPICS = {
    "isa": {
        "keyword": "ISA 계좌 비교",
        "slug": "isa-account-compare",
        "category": "금융·재테크",
        "facts": {
            "제도": "ISA(개인종합자산관리계좌)",
            "납입한도": "연 2,000만원 (5년 누적 최대 1억원, 미납분 이월 가능)",
            "의무가입기간": "3년",
            "비과세한도_일반형": "200만원",
            "비과세한도_서민형": "400만원 (총급여 5,000만원 또는 종합소득 3,800만원 이하)",
            "초과수익_과세": "9.9% 분리과세 (일반 이자·배당소득세 15.4%보다 저율)",
            "계좌유형": ["신탁형", "일임형", "중개형(투자중개형)"],
            "가입자격": "만 19세 이상 거주자, 직전연도 금융소득종합과세 대상자는 제외",
            "연금계좌_전환혜택": "만기 자금을 연금저축·IRP로 이체 시 이체액의 10%(최대 300만원) 추가 세액공제",
        },
        "key_stats": [
            ("2,000만원", "연 납입 한도"),
            ("3년", "최소 의무가입"),
            ("9.9%", "초과수익 분리과세율"),
            ("400만원", "서민형 비과세 한도"),
        ],
        # 팩트별 정밀 출처 — '어떤 수치를 어디서 가져왔는지' 명시(E-E-A-T).
        # 제목 형식: "무엇(수치) — 근거 문서·기관". deep_content가 DEFAULT_SOURCES 대신 이걸 사용.
        "sources": [
            ("비과세 한도(일반형 200만원·서민형 400만원)·초과수익 9.9% 분리과세·의무가입 3년의 법적 근거 — 조세특례제한법 제91조의18(개인종합자산관리계좌에 대한 과세특례), 국가법령정보센터",
             "https://www.law.go.kr/법령/조세특례제한법"),
            ("연 납입 한도 2,000만원(누적 1억원·미납분 이월)과 가입 자격 — 금융투자협회 'ISA 다모아' 제도 안내·유형별(신탁형/일임형/중개형) 수익률 비교 공시",
             "https://isa.kofia.or.kr"),
            ("만기 자금 연금계좌(연금저축·IRP) 전환 시 이체액 10%·최대 300만원 추가 세액공제 — 금융감독원 통합연금포털 '연금계좌 세제 안내'",
             "https://100lifeplan.fss.or.kr"),
            ("일반 금융상품 이자·배당소득 원천징수세율 15.4%(소득세 14%+지방소득세 1.4%) — 국세청 원천징수 안내",
             "https://www.nts.go.kr"),
        ],
    },
    "pension_irp": {
        "keyword": "연금저축 IRP 세액공제",
        "slug": "pension-irp-tax-deduction",
        "category": "금융·재테크",
        "facts": {
            "제도": "연금저축 vs IRP(개인형퇴직연금)",
            "세액공제_한도": "연금저축 600만원 + IRP 300만원, 합산 최대 900만원",
            "세액공제율": "총급여 5,500만원(종합소득금액 4,500만원) 이하 16.5%, 초과 13.2%",
            "최대환급액": "900만원 x 16.5% = 148만 5천원(저소득 구간), 900만원 x 13.2% = 118만 8천원(고소득 구간)",
            "효율적_납입조합": "연금저축 600만원을 먼저 채우고 나머지 300만원을 IRP에 넣는 조합이 실무에서 가장 흔함",
            "연금개시요건": "가입 후 5년 경과 + 만 55세 이후부터 연금으로 수령 가능",
            "중도해지_과세": "연금 외 형태로 수령(중도해지)하면 기타소득세 16.5% 분리과세",
            "투자상품_차이": "연금저축펀드는 위험자산 100%까지 투자 가능, IRP는 위험자산 비중 최대 70%로 제한(나머지는 원리금보장상품 등 안전자산)",
        },
        "key_stats": [
            ("900만원", "세액공제 합산 한도"),
            ("16.5%", "저소득 구간 공제율"),
            ("148만 5천원", "최대 환급액(저소득 구간)"),
            ("70%", "IRP 위험자산 투자한도"),
        ],
        "sources": [
            ("세액공제 한도(연금저축 600만원+IRP 300만원=900만원 합산)·소득구간별 공제율(16.5%/13.2%)의 법적 근거 — 국세청 '연금계좌 세액공제' 안내",
             "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7875"),
            ("최대 환급액(900만원×16.5%=148만 5천원) 계산 — YTN '연금저축·IRP 900만원 넣으면 최대 148만원 환급' 보도(2025-12-26)",
             "https://www.ytn.co.kr/_ln/0102_202512261223303080"),
            ("IRP 위험자산 투자한도 70% 규정 — 근로자퇴직급여보장법 시행령(적립금 운용방법)",
             "https://www.law.go.kr/법령/근로자퇴직급여보장법시행령"),
            ("연금저축·IRP 상품 비교 공시 — 금융감독원 통합연금포털",
             "https://100lifeplan.fss.or.kr"),
        ],
    },
    "jutaek_cheongyak": {
        "keyword": "주택청약종합저축 소득공제",
        "slug": "housing-savings-tax-deduction",
        "category": "부동산·주거",
        "facts": {
            "제도": "주택청약종합저축 소득공제",
            "소득공제_한도": "연 납입액 최대 300만원의 40%, 즉 최대 120만원까지 소득공제",
            "공제_대상요건": "총급여 7,000만원 이하 근로소득자이면서 과세기간 중 무주택 세대주(또는 세대주의 배우자)",
            "무주택확인서": "소득공제를 받으려는 과세기간의 다음 연도 2월 말까지 은행에 무주택확인서(소득공제 신청용) 제출 필요",
            "청년주택드림청약통장_대상": "만 19~34세(병역이행기간 최대 6년 인정으로 실질적으로 만 40세까지 가능), 직전년도 또는 전전년도 연소득 5,000만원 이하, 무주택자",
            "청년주택드림청약통장_혜택": "최대 금리 4.5%, 이자소득 500만원까지 비과세, 연 불입액 600만원 한도 내 소득공제, 청약 당첨 후 1년 이상 가입+1,000만원 이상 납입 시 약 2.2% 초저금리 대출 연계",
        },
        "key_stats": [
            ("120만원", "최대 소득공제액"),
            ("300만원", "연 납입 인정 한도"),
            ("4.5%", "청년주택드림 최대 금리"),
            ("500만원", "청년형 이자소득 비과세 한도"),
        ],
        "sources": [
            ("소득공제 한도(연 300만원의 40%, 최대 120만원)·무주택 세대주 요건의 법적 근거 — 조세특례제한법 제87조(주택청약종합저축 등에 대한 소득공제)",
             "https://www.law.go.kr/LSW/lsLawLinkInfo.do?lsJoLnkSeq=1000819880&lsId=001584"),
            ("공제 대상 요건(총급여 7,000만원 이하·무주택 세대주)·무주택확인서 제출 기한 — 국세청 '주택마련저축 소득공제' 안내",
             "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=40610&cntntsId=239022"),
            ("청년주택드림청약통장 가입대상·금리·비과세·연계대출 조건 — 국토교통부 청년주택드림청약 공식 안내",
             "https://www.molit.go.kr/2024dreamaccount"),
            ("청년·신혼부부 주거지원 제도 종합 안내 — 마이홈(국토교통부 산하 주거복지포털)",
             "https://www.myhome.go.kr"),
        ],
    },
    "earn_income_credit": {
        "keyword": "근로장려금 신청 자격 금액",
        "slug": "earned-income-tax-credit",
        "category": "세금·절세",
        "facts": {
            "제도": "근로장려금(근로연계형 소득지원)",
            "정기신청_기간": "매년 5월 1일~5월 31일(2026년도 정기신청 동일)",
            "기한후_신청": "6월 1일~11월 30일 — 지급액 95%만 지급(5% 감액)",
            "단독가구_소득기준": "부부합산 총소득 2,200만 원 미만",
            "단독가구_최대지급": "165만 원",
            "홑벌이_소득기준": "부부합산 총소득 3,200만 원 미만",
            "홑벌이_최대지급": "285만 원",
            "맞벌이_소득기준": "부부합산 총소득 4,400만 원 미만(2025년 귀속부터 기준 완화)",
            "맞벌이_최대지급": "330만 원",
            "재산_기준": "가구원 전체 재산 합계 2억 4,000만 원 미만(6월 1일 기준)",
            "재산_50%_구간": "1억 7,000만~2억 4,000만 원 미만이면 산정액의 50%만 지급",
            "신청_채널": "국세청 홈택스·손택스·ARS(1544-9944)",
        },
        "key_stats": [
            ("330만원", "맞벌이 최대 지급"),
            ("4,400만원", "맞벌이 소득 상한"),
            ("2.4억원", "재산 기준"),
            ("5월 31일", "정기신청 마감"),
        ],
        "sources": [
            ("가구별 소득기준·최대지급액(단독 165만·홑벌이 285만·맞벌이 330만) — 국세청 '근로장려금 소개'",
             "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7781&mi=2450"),
            ("정기신청 기간·기한 후 5% 감액·재산 2.4억 기준 — 국세청 장려금 안내",
             "https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?mi=2450"),
            ("맞벌이 소득기준 4,400만 원 완화(2025년 귀속) — 국세청 보도·홈택스 안내",
             "https://www.hometax.go.kr"),
        ],
    },
    "housing_benefit": {
        "keyword": "주거급여 신청 자격 금액",
        "slug": "housing-benefit-guide",
        "category": "부동산·주거",
        "facts": {
            "제도": "주거급여(임차급여·수선유지급여)",
            "선정기준": "소득인정액이 기준 중위소득 48% 이하",
            "4인가구_소득인정액_상한": "월 3,117,474원(2026년)",
            "1인가구_소득인정액_상한": "월 1,230,834원(2026년)",
            "서울_1인_기준임대료": "월 369,000원(1급지, 2026년)",
            "서울_4인_기준임대료": "월 571,000원(1급지, 2026년)",
            "전액지원_조건": "소득인정액 ≤ 생계급여 선정기준(32%)이면 기준임대료 전액 지원",
            "자기부담_조건": "생계급여 선정기준 초과 시 (소득인정액−생계기준)×30%를 자기부담으로 공제",
            "신청_채널": "복지로(bokjiro.go.kr) 또는 주소지 읍·면·동 행정복지센터",
            "대상_주거": "임차급여는 타인 소유 주택 임차 가구(임대차계약·전입신고 필요)",
        },
        "key_stats": [
            ("311만원", "4인 소득인정 상한"),
            ("57.1만원", "서울 4인 기준임대료"),
            ("48%", "중위소득 선정비율"),
            ("369,000원", "서울 1인 기준임대료"),
        ],
        "sources": [
            ("2026년 주거급여 선정기준(중위 48%)·기준임대료 — 국토교통부 고시 제2025-506호",
             "https://www.molit.go.kr/USR/I0204/m_45/dtl.jsp?idx=18653"),
            ("소득인정액·신청 절차·임차급여 산정 — 마이홈 주거급여 안내",
             "https://www.myhome.go.kr/hws/portal/cont/selectHousingBenefitView.do"),
            ("주거급여 신청·서류·자기부담 산정 — LH 주거복지사업 안내",
             "https://www.lh.or.kr/menu.es?mid=a10401050100"),
        ],
    },
    "health_insurance": {
        "keyword": "5세대 실손보험 비교",
        "slug": "5th-gen-health-insurance",
        "category": "보험",
        "facts": {
            "제도": "5세대 실손의료보험(2026년 5월 출시)",
            "보험료_변화": "4세대 대비 보험료 약 30% 수준 인하(구조·특약 선택에 따라 상이)",
            "중증_비급여_특약1": "한도 5,000만 원·자기부담률 30% 유지, 상급·종합병원 입원 연간 자기부담 500만 원 초과분 추가 보장",
            "비중증_비급여_특약2": "연간 한도 1,000만 원, 입원 자기부담률 50% 등(4세대 대비 축소·상향)",
            "보장_제외_항목": "도수치료·체외충격파·비급여 주사제 등 과잉이용 우려 항목은 특약2에서도 제외 또는 대폭 축소",
            "급여_통원_변화": "외래 급여 자기부담률이 건강보험 본인부담률과 연동(의원 30%·상급종합 60% 등)",
            "급여_입원": "입원 급여 자기부담률 20% 유지",
            "신규_보장": "임신·출산 급여 의료비, 발달장애 급여 의료비 신규 포함",
            "전환_시점": "4세대 재가입·갱신 시점에 5세대 전환 선택 가능(개인별 보장·보험료 비교 필요)",
        },
        "key_stats": [
            ("30%", "4세대 대비 보험료↓"),
            ("5,000만원", "중증 비급여 한도"),
            ("1,000만원", "비중증 한도"),
            ("500만원", "중증 입원 부담 상한"),
        ],
        "sources": [
            ("5세대 실손 구조(중증·비중증 특약 분리·급여 연동·신규 보장) — 금융위원회 보도자료",
             "https://www.fsc.go.kr/no010101/86831"),
            ("보장 범위·자기부담률·전환 시 유의사항 — 금융감독원 보험 안내",
             "https://www.fss.or.kr"),
            ("공식 비교·상품 공시 — 내보험찾아줌(cont.insure.or.kr)",
             "https://cont.insure.or.kr"),
        ],
    },
    "unemployment_benefit": {
        "keyword": "실업급여 수급기간 금액",
        "slug": "unemployment-benefit-guide",
        "category": "정부지원·혜택",
        "facts": {
            "제도": "구직급여(실업급여)",
            "산정_공식": "퇴직 전 3개월 1일 평균임금의 60%(이직일 2019.10.1 이후)",
            "1일_상한액": "68,100원(2026년, 고용노동부 고시 기준 — 매년 조정)",
            "1일_하한액": "66,048원(2026년 최저시급 10,320원×8시간×80%)",
            "수급자격_핵심": "비자발적 이직·고용보험 180일 이상·수급기간(이직 다음날~12개월) 내 실업신고·구직활동",
            "소정급여일수_예시_50미만_3년": "고용보험 3~5년 미만 가입 시 180일(50세 미만)",
            "소정급여일수_최대": "270일(50세 이상·장애인, 10년 이상 가입)",
            "신청_장소": "거주지 관할 고용센터(고용24·고용보험 모바일)",
            "면책_확인": "정확한 일액·일수는 이직일·가입기간·임금에 따라 달라 고용센터 조회 필수",
        },
        "key_stats": [
            ("68,100원", "1일 상한(2026)"),
            ("60%", "평균임금 비율"),
            ("180일", "3~5년·50세미만 예시"),
            ("12개월", "수급기간 한도"),
        ],
        "sources": [
            ("구직급여 산정·상·하한액·소정급여일수 — 고용24 '실업급여란'",
             "https://ei.work24.go.kr/ei/eim/eg/ei/eiEminsr/retrievePb0201Info.do"),
            ("실업 신고·수급자격·구직활동 — 고용보험(ei.go.kr) 안내",
             "https://www.ei.go.kr"),
            ("2026년 최저임금·하한액 산정 — 고용노동부 최저임금 고시",
             "https://www.moel.go.kr"),
        ],
    },
}


def _doc(title, r):
    css = """
:root{--fg:#1f2328;--muted:#6a737d;--line:#e5e7eb;--accent:#2f6f4f;--accent-bg:#eef6f1;--tableh:#f3f5f7;--soft:#fafbfc}
*{box-sizing:border-box}body{margin:0;background:#f3f4f6;color:var(--fg);font-family:'Malgun Gothic',system-ui,sans-serif;line-height:1.75}
.mocknote{max-width:800px;margin:14px auto 0;padding:9px 14px;border:1px dashed #b9c0c7;border-radius:8px;background:#fff;color:#6a737d;font-size:12.5px}
.wrap{max-width:800px;margin:12px auto 48px;background:#fff;padding:40px 44px 48px;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.crumb{font-size:13px;color:var(--muted);margin-bottom:14px}.crumb .here{color:var(--accent);font-weight:600}
h1{font-size:28px;line-height:1.38;margin:4px 0 12px}
.metaline{color:var(--muted);font-size:13px;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:22px}.metaline b{color:#414852}
.hj-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0}
.hj-stat{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:13px 8px;text-align:center}
.hj-stat-v{font-size:19px;font-weight:800;color:var(--accent)}.hj-stat-l{font-size:12px;color:var(--muted);margin-top:3px;line-height:1.4}
.hj-toc{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:20px 0}
.hj-toc-t{font-size:13px;font-weight:800;color:#414852;margin-bottom:8px}.hj-toc ol{margin:0;padding-left:20px}.hj-toc li{margin:4px 0;font-size:14.5px}.hj-toc a{color:#2b5a86;text-decoration:none}
.wrap p{margin:0 0 16px;font-size:16.5px}
.wrap h2{font-size:21.5px;border-top:1px solid var(--line);margin-top:34px;padding-top:26px;margin-bottom:13px}
.wrap ul,.wrap ol{margin:0 0 17px;padding-left:22px}.wrap li{margin:0 0 8px;font-size:16.5px}
.hj-summary{background:var(--accent-bg);border-left:4px solid var(--accent);border-radius:8px;padding:17px 21px;margin:24px 0}
.hj-summary-title{font-weight:800;color:var(--accent);margin:0 0 9px!important;font-size:14.5px}.hj-summary ul{margin:0;padding-left:2px;list-style:none}
.hj-summary li{position:relative;padding-left:23px;margin-bottom:7px;font-size:15.5px}.hj-summary li:before{content:'✓';position:absolute;left:0;color:var(--accent);font-weight:800}
.hj-table{margin:22px 0;overflow-x:auto}.hj-table table{border-collapse:collapse;width:100%;font-size:14.5px;min-width:520px}
.hj-table th,.hj-table td{border:1px solid var(--line);padding:10px 12px;text-align:left}.hj-table thead th{background:var(--tableh);font-weight:700}.hj-table tbody td:first-child{font-weight:600;background:var(--soft)}
.hj-faq-item{border:1px solid var(--line);border-radius:10px;padding:15px 19px;margin-bottom:11px}.hj-faq-q{margin:0 0 7px;font-size:15.5px;color:var(--accent)}.hj-faq-a{margin:0;color:#33393f;font-size:15.5px}
.hj-photo{margin:20px 0;border:1px dashed #c7ccd1;border-radius:8px;height:120px;display:flex;align-items:center;justify-content:center;color:#9aa0a6;font-size:13px;background:var(--soft)}.hj-photo:after{content:'[이미지 슬롯]'}
.hj-sources{margin-top:34px}.hj-sources h2{font-size:16px;border:0;padding:0;margin:0 0 10px}.hj-sources ul{padding-left:20px}.hj-sources li{font-size:14px;margin-bottom:6px}.hj-sources a{color:#2b5a86}
.hj-disclaimer{margin-top:20px;background:#fbf7ee;border:1px solid #ecdfc3;border-radius:10px;padding:14px 18px;font-size:13.5px;color:#6d5f43;line-height:1.65}
@media(max-width:640px){.wrap{padding:24px 16px}.hj-stats{grid-template-columns:1fr 1fr}h1{font-size:22px}}
"""
    return (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{r["seo_title"]}</title><meta name="description" content="{r["meta_description"]}">'
        f'{r["schema_jsonld"]}<style>{css}</style></head><body>'
        f'<div class="mocknote">◇ WP 심층분석 <b>DRY_RUN</b>(자동 생성) — deep_content + wp_render 실제 산출 · 발행 안 함</div>'
        f'<article class="wrap"><nav class="crumb"><span>홈</span> › <span class="here">{r["tags"][0] if r["tags"] else ""}</span></nav>'
        f'<h1>{title}</h1><div class="metaline">글 <b>현지언니</b> · 게시 2026.07.07 · 심층분석</div>'
        f'{r["content_html"]}</article></body></html>'
    )


def run():
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY 없음 — 종료(로컬은 GH Actions로 실행)")
        sys.exit(1)
    topic_id = os.environ.get("WP_TOPIC", "isa").strip().lower()
    topic = TOPICS.get(topic_id)
    if not topic:
        logger.error(f"알 수 없는 WP_TOPIC: {topic_id!r} (가능: {list(TOPICS)})")
        sys.exit(1)

    logger.info(f"[DRY_RUN] 심층분석 생성 시작: {topic_id}")
    post = generate_deep_post(topic, GOOGLE_API_KEY)
    if not post:
        logger.error("생성 실패 — 종료")
        sys.exit(1)

    r = render_wordpress_post(post, category=topic["category"])
    logger.info(f"제목: {post['title']}")
    logger.info(f"slug: {r['slug']}")
    logger.info(f"content_html {len(r['content_html'])}자 · 목차 {'있음' if r['toc_html'] else '없음'} · "
                f"핵심수치 {'있음' if r['key_stats_html'] else '없음'} · 출처 {'있음' if r['sources_html'] else '없음'}")

    out_dir = os.path.join(DATA_DIR, "screenshots")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"wp_dry_{r['slug']}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(_doc(post["title"], r))
    logger.info(f"[DRY_RUN] HTML 저장: {out}")
    logger.info("===== 본문(마커) =====\n" + post.get("body", "")[:800] + "\n=====")


if __name__ == "__main__":
    run()
