#!/bin/bash
# paper_tracker_daily.sh — v2: 완전한 데이터 파이프라인
# 매일 장 마감 후 포트폴리오 성과 + 매크로 분석 → GitHub push → Vercel
# 각 단계 실패해도 전체 중단 없이 진행 (|| true)
set +e  # 각 단계 실패 시 계속 진행
set -u  # undefined 변수는 에러
set -o pipefail  # 파이프 실패 감지

REPO_DIR="/tmp/hermes-paper-portfolio"
DATA_DIR="$HOME/trade-pipeline/data"
SCRIPT_DIR="$HOME/trade-pipeline/scripts"
FAIL=0

echo "[$(date '+%Y-%m-%d %H:%M')] 📊 Daily Pipeline 시작"

# 1. 포트폴리오 성과 계산 (LLM 미사용, 순수 Python)
cd "$HOME/trade-pipeline" || { echo "  ❌ cd 실패"; FAIL=1; }
echo "  → paper_tracker.py"
python3 "$SCRIPT_DIR/paper_tracker.py" 2>&1 | tail -3 || { echo "  ⚠️ paper_tracker.py 실패 (계속 진행)"; FAIL=1; }

# 2. 매크로 대시보드 데이터 생성 (Risk Score + 추천)
echo "  → generate_macro_dashboard.py"
python3 "$SCRIPT_DIR/generate_macro_dashboard.py" 2>&1 | grep -E "(✅|CAGR|MDD|Sharpe)" || { echo "  ⚠️ macro_dashboard 실패 (계속 진행)"; FAIL=1; }

# 3. 매크로 PNG 플롯 생성
echo "  → generate_macro_plots.py"
python3 "$SCRIPT_DIR/generate_macro_plots.py" 2>&1 | grep "✅" || { echo "  ⚠️ macro_plots 실패 (계속 진행)"; FAIL=1; }

# 4. 컨세서스 데이터 수집 (EPS/매출/목표가)
echo "  → collect_consensus.py"
python3 "$SCRIPT_DIR/collect_consensus.py" 2>&1 | grep -E "(✅|→|❌)" || { echo "  ⚠️ consensus 수집 실패 (계속 진행)"; }

# 5. 포트폴리오 비중 자동 복원 (전 종목 2%인 경우 macro 기반 복원)
echo "  → fix_portfolio_weights.py"
python3 "$SCRIPT_DIR/fix_portfolio_weights.py" 2>&1 | grep -E "(✅|⚠️|❌)" || true

# 5. 포트폴리오 성과 재계산 (복원된 비중 반영)
echo "  → paper_tracker.py (재실행)"
python3 "$SCRIPT_DIR/paper_tracker.py" 2>&1 | tail -3 || { echo "  ⚠️ paper_tracker 재실행 실패 (계속 진행)"; FAIL=1; }

# 6. 매크로 추천 → 포트폴리오 매핑 (복원 후 재계산)
echo "  → compute_portfolio_target.py"
python3 "$SCRIPT_DIR/compute_portfolio_target.py" 2>&1 | grep "✅" || { echo "  ⚠️ portfolio_target 실패 (계속 진행)"; FAIL=1; }

# 5. GitHub 레포 준비
if [ ! -d "$REPO_DIR" ]; then
    cd /tmp
    echo "  → Cloning Vercel repo..."
    git clone "https://$(grep -oP 'GITHUB_TOKEN=\K.*' ~/.hermes/.env | tr -d '"')@github.com/mybotagent/hermes-paper-portfolio.git" "$REPO_DIR"
fi

# 6. 데이터 파일만 복사 (대시보드 포맷은 고정)
cd "$REPO_DIR"
cp "$DATA_DIR/portfolio_dashboard.html" index.html
cp "$DATA_DIR/paper_tracker_daily.csv" .
cp "$DATA_DIR/paper_tracker_holdings.csv" .
cp "$DATA_DIR/paper_tracker_metrics.json" .
cp "$DATA_DIR/paper_tracker_market.csv" .
cp "$DATA_DIR/paper_tracker_sp500.csv" .
cp "$DATA_DIR/macro_dashboard_data.json" .
cp "$DATA_DIR/macro_regime_history.csv" .
cp "$DATA_DIR/macro_plots_status.json" .
cp "$DATA_DIR/portfolio_target.json" .
# PNG plots
mkdir -p macro_plots
cp "$DATA_DIR/macro_plots/"*.png macro_plots/

# 7. Git Push (데이터만)
git add -A
if git diff --cached --quiet; then
    echo "  → 변경사항 없음"
else
    git commit -m "📊 data update $(date '+%Y-%m-%d')" --quiet
    git push origin main 2>&1 | tail -2
    echo "  ✅ GitHub push 완료 → Vercel 자동 배포"
fi

echo "[$(date '+%Y-%m-%d %H:%M')] ✅ Daily Pipeline 완료"

# Health Check 실행 (통과/실패 무관, 기록용)
python3 "$SCRIPT_DIR/pipeline_healthcheck.py" 2>&1 | tail -6

exit $FAIL
