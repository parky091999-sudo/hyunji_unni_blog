#!/bin/bash
# hyunjiunni.com 워드프레스 초기 설정 (WP-CLI)
set -euo pipefail
WP="sudo -u www-data wp --path=/var/www/html"
BASE="https://hyunjiunni.com"

echo "== 사이트 옵션 =="
$WP option update blogname '현지언니'
$WP option update blogdescription '놓치기 쉬운 돈·제도 정보를 발품 팔아 쉽게 정리합니다'
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

echo "== 카테고리 slug·설명 =="
declare -A CAT_SLUG=(
  ['정부지원·혜택']='gov-support'
  ['금융·재테크']='finance'
  ['세금·절세']='tax-saving'
  ['보험']='insurance'
  ['부동산·주거']='housing'
  ['주식']='stock'
)
declare -A CAT_DESC=(
  ['정부지원·혜택']='정부 지원금·혜택·신청 방법'
  ['금융·재테크']='연금·ISA·퇴직연금·재테크 심층 분석'
  ['세금·절세']='연말정산·소득공제·절세 전략'
  ['보험']='실손·자동차·연금보험 비교와 공식 도구 안내'
  ['부동산·주거']='전세·청약·주거급여·주택 관련 제도'
  ['주식']='ETF·공모주·종목 심층 분석'
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
$WP term update category 1 --slug=uncategorized 2>/dev/null || true

echo "== 네비게이션(헤더) =="
NAV_FILE=$(mktemp)
cat > "$NAV_FILE" << 'NAVEOF'
<!-- wp:navigation-link {"label":"홈","url":"https://hyunjiunni.com/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"정부지원·혜택","url":"https://hyunjiunni.com/category/gov-support/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"금융·재테크","url":"https://hyunjiunni.com/category/finance/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"세금·절세","url":"https://hyunjiunni.com/category/tax-saving/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"보험","url":"https://hyunjiunni.com/category/insurance/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"부동산·주거","url":"https://hyunjiunni.com/category/housing/","kind":"custom","isTopLevelLink":true} /-->

<!-- wp:navigation-link {"label":"주식","url":"https://hyunjiunni.com/category/stock/","kind":"custom","isTopLevelLink":true} /-->
NAVEOF
$WP post update 4 --post_content="$(cat "$NAV_FILE")"
rm -f "$NAV_FILE"

echo "== 소개 페이지 =="
ABOUT_ID=$($WP post list --post_type=page --name=about --field=ID --format=ids 2>/dev/null || true)
if [ -z "$ABOUT_ID" ]; then
  $WP post create --post_type=page --post_title='소개' --post_name=about --post_status=publish \
    --post_content='<!-- wp:paragraph --><p>안녕하세요, 생활정보 큐레이터 <strong>현지언니</strong>입니다.</p><!-- /wp:paragraph --><!-- wp:paragraph --><p>2030 신혼·1인가구가 놓치기 쉬운 <strong>돈·제도·혜택</strong>을 직접 발품 팔아 정확하고 쉽게 정리합니다.</p><!-- /wp:paragraph -->'
else
  echo "소개 페이지 이미 존재 id=$ABOUT_ID"
fi

echo "== 개인정보 처리방침 =="
$WP post update 3 --post_name=privacy --post_status=publish \
  --post_content='<!-- wp:heading --><h2>개인정보 처리방침</h2><!-- /wp:heading --><!-- wp:paragraph --><p>현지언니(hyunjiunni.com)는 방문자 개인정보를 최소한으로 수집·이용합니다. Google Analytics·애드센스 연동 시 해당 사업자 정책이 적용될 수 있습니다.</p><!-- /wp:paragraph -->' \
  2>/dev/null || true

echo "== 글 slug·카테고리 정리 =="
$WP post update 9 --post_name=isa-account-compare 2>/dev/null || true
FIN_ID=$($WP term list category --slug=finance --field=term_id 2>/dev/null | head -1 || true)
if [ -n "$FIN_ID" ] && [ "$FIN_ID" != "0" ]; then
  $WP post term set 9 category "$FIN_ID" --by=id 2>/dev/null || true
fi

echo "== Hello World·샘플 글 정리 =="
$WP post delete 1 --force 2>/dev/null || true

echo "== 사이트 아이콘(favicon) =="
MU="/var/www/html/wp-content/mu-plugins"
if [ -f "$MU/hyunji-favicon.png" ]; then
  ICON_ID=$($WP media import "$MU/hyunji-favicon.png" --porcelain 2>/dev/null || true)
  if [ -n "$ICON_ID" ]; then
    $WP option update site_icon "$ICON_ID"
    echo "site_icon=$ICON_ID"
  fi
fi

echo "== 플러그인 정리 =="
$WP plugin deactivate hello 2>/dev/null || true

echo "== rewrite flush =="
$WP rewrite flush

echo "== 완료 =="
$WP term list category --fields=term_id,name,slug,count
$WP option get blogname
$WP option get blogdescription
