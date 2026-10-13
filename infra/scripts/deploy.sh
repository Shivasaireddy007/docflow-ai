#!/usr/bin/env bash
# Rolls a new pipeline image out to every step as a canary: CodeDeploy shifts 10% of the "live"
# alias to the new version for 5 minutes, then the rest, and rolls back if the step's error
# alarm fires.
#   infra/scripts/deploy.sh <image-uri> [name-prefix]
set -euo pipefail
IMAGE="$1"
PREFIX="${2:-docflow-demo}"

for step in prepare ocr extract decide; do
  fn="$PREFIX-$step"
  echo "== $fn"
  aws lambda update-function-code --function-name "$fn" --image-uri "$IMAGE" --output text --query LastUpdateStatus > /dev/null
  aws lambda wait function-updated-v2 --function-name "$fn"
  new=$(aws lambda publish-version --function-name "$fn" --query Version --output text)
  current=$(aws lambda get-alias --function-name "$fn" --name live --query FunctionVersion --output text)
  if [ "$new" = "$current" ]; then
    echo "already live at version $new"
    continue
  fi
  appspec=$(jq -cn --arg fn "$fn" --arg from "$current" --arg to "$new" '{
    version: 0.0,
    Resources: [{step: {Type: "AWS::Lambda::Function",
      Properties: {Name: $fn, Alias: "live", CurrentVersion: $from, TargetVersion: $to}}}]
  }')
  deployment=$(aws deploy create-deployment \
    --application-name "$PREFIX-pipeline" --deployment-group-name "$step" \
    --revision "$(jq -cn --arg c "$appspec" '{revisionType: "AppSpecContent", appSpecContent: {content: $c}}')" \
    --query deploymentId --output text)
  echo "canary $deployment: version $current -> $new"
  aws deploy wait deployment-successful --deployment-id "$deployment"
done
echo "All steps live."
