#!/bin/bash
# hyunjiunni.com 워드프레스 초기 설정 — 수익 허브 6종 (2026-07-09)
set -euo pipefail
WP="sudo -u www-data wp --path=/var/www/html"
BASE="https://hyunjiunni.com"

echo "== 사이트 옵션 =="
$WP option update blogname '현지언니'
$WP option update blogdescription '정부 제도·세금·연금·보험·주거를 공식 자료 기준으로 분석하는 생활금융 칼럼'
$WP option update timezone_string 'Asia/Seoul'
$WP option update permalink_structure '/%postname%/'
$WP option update WPLANG 'ko_KR'
$WP option update blog_public 1
$WP option update default_comment_status closed
$WP option update posts_per_page 10
$WP option update show_on_front posts
$WP option update date_format 'Y년 n월 j일'
$WP option update time_format 'G:i'
$WP option update start_of_week 1

echo "== 수익 허브 카테고리 =="
declare -A CAT_SLUG=(
  ['연금·절세 설계']='pension-tax'
  ['대출·신용 전략']='loan-credit'
  ['보험·리스크 설계']='insurance-risk'
  ['세금·환급 가이드']='tax-refund'
  ['주거·청약 전략']='housing-plan'
  ['제도·복지 해설']='policy-benefit'
)
declare -A CAT_DESC=(
  ['연금·절세 설계']='ISA·연금저축·IRP·퇴직연금 세액공제와 장기 절세 전략 심층 분석'
  ['대출·신용 전략']='전세·담보·대환대출 금리 비교와 신용점수 개선 시뮬레이션'
  ['보험·리스크 설계']='실손·자동차·진단비 보장 구조 비교와 갱신·전환 의사결정'
  ['세금·환급 가이드']='연말정산·근로장려금·양도세 환급 시뮬레이션과 절세 순서'
  ['주거·청약 전략']='청약·전세·취득세·LTV 통합 프레임과 5년 주거비 시뮬'
  ['제도·복지 해설']='실업급여·주거급여·에너지 지원 자격 경계값 계산'
)
for name in "${!CAT_SLUG[@]}"; do
  slug="${CAT_SLUG[$name]}"
  desc="${CAT_DESC[$name]}"
  tid=$($WP term list category --name="$name" --field=term_id 2>/dev/null | head -1 || true)
  if [ -n "$tid" ]; then
    $WP term update category "$tid" --slug="$slug" --description="$desc"
  else
    $WP term create category "$name" --slug="$slug" --description="$desc"
  fi
done

echo "== 레거시 카테고리 정리(미사용 숨김) =="
for old in "정부지원·혜택" "금융·재테크" "세금·절세" "보험" "부동산·주거" "주식"; do
  tid=$($WP term list category --name="$old" --field=term_id 2>/dev/null | head -1 || true)
  if [ -n "$tid" ]; then
    $WP term update category "$tid" --description="(구 카테고리 — 신규 글은 수익 허브 사용)" 2>/dev/null || true
  fi
done

echo "== 네비게이션 =="
NAV_FILE=$(mktemp)
cat > "$NAV_FILE" << 'NAVEOF'
<!-- wp:navigation-link {"label":"홈","url":"https://hyunjiunni.com/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"연금·절세","url":"https://hyunjiunni.com/category/pension-tax/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"대출·신용","url":"https://hyunjiunni.com/category/loan-credit/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"보험·리스크","url":"https://hyunjiunni.com/category/insurance-risk/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"세금·환급","url":"https://hyunjiunni.com/category/tax-refund/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"주거·청약","url":"https://hyunjiunni.com/category/housing-plan/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"제도·복지","url":"https://hyunjiunni.com/category/policy-benefit/","kind":"custom","isTopLevelLink":true} /-->
NAVEOF
$WP post update 4 --post_content="$(cat "$NAV_FILE")"
rm -f "$NAV_FILE"

echo "== 소개 페이지 =="
ABOUT_ID=$($WP post list --post_type=page --name=about --field=ID --format=ids 2>/dev/null || true)
if [ -n "$ABOUT_ID" ]; then
  $WP post update "$ABOUT_ID" --post_content='<!-- wp:paragraph --><p><strong>현지언니</strong>는 정부 제도·세금·연금·보험·주거를 <strong>공식 자료 기준</strong>으로 분석하는 생활금융 칼럼입니다.</p><!-- /wp:paragraph --><!-- wp:paragraph --><p>네이버 블로그의 실용 가이드와 달리, 이 사이트는 비교·계산·상황별 판단 기준을 깊게 다룹니다. 수치는 국세청·금감원·국토부 등 공시 자료를 우선 인용합니다.</p><!-- /wp:paragraph -->'
fi

echo "== 작성자 URL =="
$WP user update 1 --user_url="$BASE" 2>/dev/null || true

echo "== rewrite flush =="
$WP rewrite flush

echo "== 완료 =="
$WP term list category --fields=term_id,name,slug,count
