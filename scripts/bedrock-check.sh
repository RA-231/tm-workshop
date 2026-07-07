#!/usr/bin/env bash
# Validate the workshop AWS credential against Bedrock BEFORE bringing up
# LiteLLM/LibreChat. Read-only: confirms who you are, lists the inference
# profiles the account can see, and cross-checks the model IDs pinned in
# litellm/config.yaml so a typo or a not-enabled model surfaces here instead
# of as a silent per-model failure in the chat UI.
#
#   task bedrock:check
#
# Requires the IAM user to allow the read actions (ListInferenceProfiles,
# ListFoundationModels) in addition to InvokeModel.
set -euo pipefail

# Pull AWS_* out of .env without echoing secrets.
if [[ -f .env ]]; then
  set -a; . ./.env; set +a
fi
export AWS_REGION="${AWS_REGION_NAME:-us-east-1}"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found — install it or verify model IDs by hand." >&2
  exit 1
fi

echo "== caller identity =="
aws sts get-caller-identity --query '{account:Account,arn:Arn}' --output table

echo
echo "== system-defined inference profiles (us.* are cross-region) =="
aws bedrock list-inference-profiles --type-equals SYSTEM_DEFINED \
  --query 'inferenceProfileSummaries[].inferenceProfileId' --output text \
  | tr '\t' '\n' | sort | tee /tmp/bedrock-profiles.txt

echo
echo "== model IDs pinned in litellm/config.yaml vs. what's visible =="
# Grep the bedrock/... IDs out of the config, strip the bedrock/ prefix.
grep -oE 'bedrock/[a-z0-9.:-]+' litellm/config.yaml | sed 's|bedrock/||' | sort -u \
| while read -r id; do
    if grep -qxF "$id" /tmp/bedrock-profiles.txt; then
      echo "  ok       $id"
    else
      # Region-scoped models (e.g. openai.*) aren't inference profiles; check
      # the foundation-model list too before calling it missing.
      if aws bedrock list-foundation-models \
           --query 'modelSummaries[].modelId' --output text 2>/dev/null \
           | tr '\t' '\n' | grep -qxF "$id"; then
        echo "  ok (fm)  $id"
      else
        echo "  MISSING  $id   <- not visible; enable model access or fix the ID"
      fi
    fi
  done

echo
echo "Done. 'MISSING' means the ID isn't visible to this credential — either the"
echo "model isn't enabled under Bedrock > Model access, or the ID needs fixing."
