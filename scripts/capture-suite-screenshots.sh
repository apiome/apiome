#!/usr/bin/env bash
# Capture screenshots of the /mockups/* design surfaces for use on the
# apiome-web /suite landing pages. Uses the system Chrome in
# headless mode — no Playwright/Puppeteer browsers required.
#
# Output:
#   apiome-web/public/suite/<slug>-cover.png    (main spotlight image)
#   apiome-web/public/suite/<slug>-hub.png      (mockup hub / index)
#   apiome-web/public/suite/<slug>-detail-1..N  (extra feature shots)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOCKUPS="$ROOT/apiome-ui/public/mockups"
OUT="$ROOT/apiome-web/public/suite"

mkdir -p "$OUT"

shoot() {
  local html="$1"
  local png="$2"
  if [[ ! -f "$html" ]]; then
    echo "  skip (missing): $html"
    return 0
  fi
  google-chrome \
    --headless \
    --disable-gpu \
    --hide-scrollbars \
    --no-sandbox \
    --window-size=1440,900 \
    --virtual-time-budget=2000 \
    --screenshot="$png" \
    "file://$html" >/dev/null 2>&1
  echo "  -> $(basename "$png")"
}

# slug : cover : hub : extras...
declare -a JOBS=(
  "academy:student-dashboard.html:index.html:catalog.html:course-detail.html:lesson-viewer.html"
  "analytics:executive-dashboard.html:index.html:api-analytics.html:schema-analytics.html:export-center.html"
  "architect:landscape.html:index.html:data-flow.html:impact-analysis.html:adrs.html"
  "automation:dashboard.html:index.html:webhooks.html:jobs.html:integrations.html"
  "browser:tenant-home.html:index.html:version-viewer.html:compare.html:playground.html"
  "code-gen:studio.html:index.html:client-sdk.html:server-stubs.html:mock-data.html"
  "collaboration:workspace.html:index.html:comments.html:diff-viewer.html:approvals.html"
  "connect:dashboard.html:index.html:mapping-editor.html:event-router.html:marketplace.html"
  "contracts:dashboard.html:index.html:terms-editor.html:billing.html:consent.html"
  "data-insights:dashboard-builder.html:index.html:health-score.html:funnels.html:revenue.html"
  "data-shield:dashboard.html:index.html:firewall.html:anomalies.html:vault.html"
  "data-transform:dashboard.html:index.html:rule-editor.html:migration-plan-detail.html:spark-jobs.html"
  "db:dashboard.html:index.html:nl-query.html:relationship-graph.html:vector-search.html"
  "detective:dashboard.html:index.html:lineage-graph.html:investigations.html:reconciliation.html"
  "import:dashboard.html:index.html:multi-source.html:transforms.html:approvals.html"
  "linting:quality-score.html:index.html:editor-validation.html:rule-config.html:breaking-changes.html"
)

for job in "${JOBS[@]}"; do
  IFS=':' read -r -a parts <<< "$job"
  slug="${parts[0]}"
  cover="${parts[1]}"
  hub="${parts[2]}"
  echo "[$slug]"
  shoot "$MOCKUPS/$slug/$cover" "$OUT/$slug-cover.png"
  shoot "$MOCKUPS/$slug/$hub"   "$OUT/$slug-hub.png"
  i=1
  for ((k=3; k<${#parts[@]}; k++)); do
    shoot "$MOCKUPS/$slug/${parts[$k]}" "$OUT/$slug-detail-$i.png"
    i=$((i+1))
  done
done

echo
echo "All screenshots written to: $OUT"
