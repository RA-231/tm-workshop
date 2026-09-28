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

# Pull AWS_* out of .env without echoing secrets -- and without EXECUTING the
# file. `. ./.env` would run anything in it: a value like $(curl ...|sh), or a
# backtick, executes the moment the file is sourced. Since .env is filled in by
# hand from a card people scan, it is not a file this script should execute.
# Each line is read literally and assigned; nothing is expanded or evaluated.
load_env() {
  local file="${1}" line name value lineno=0 skipped=0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    lineno=$((lineno + 1))
    line="${line%$'\r'}"                               # CRLF editors
    [[ ${lineno} -eq 1 ]] && line="${line#$'\xef\xbb\xbf'}"   # UTF-8 BOM
    line="${line#"${line%%[![:space:]]*}"}"             # trim left
    line="${line%"${line##*[![:space:]]}"}"             # trim right
    [[ -z "${line}" || "${line}" == '#'* ]] && continue
    line="${line#export }"                              # 'export FOO=bar' habit
    if [[ "${line}" != *=* ]]; then
      echo "warning: .env line ${lineno} is not NAME=value, ignoring" >&2
      skipped=$((skipped + 1)); continue
    fi
    name="${line%%=*}"; value="${line#*=}"
    name="${name%"${name##*[![:space:]]}"}"             # 'NAME = value'
    value="${value#"${value%%[![:space:]]*}"}"
    if [[ ! "${name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "warning: .env line ${lineno} has an odd variable name (${name}), ignoring" >&2
      skipped=$((skipped + 1)); continue
    fi
    if [[ "${value}" == '"'*'"' || "${value}" == "'"*"'" ]]; then
      value="${value:1:${#value}-2}"                    # one layer of quotes
    elif [[ "${value}" =~ ^(.*[^[:space:]])[[:space:]]+#.* ]]; then
      value="${BASH_REMATCH[1]}"                        # trailing ' # comment'
    fi
    value="${value%"${value##*[![:space:]]}"}"
    # An empty assignment never overwrites a real value. .env.example ships
    # empty placeholders; pasting a credential ABOVE them would otherwise be
    # silently undone by the placeholder further down the file.
    [[ -z "${value}" ]] && continue
    export "${name}=${value}"                           # literal: no expansion
  done < "${file}"
  [[ ${skipped} -gt 0 ]] && echo "note: ignored ${skipped} unparseable .env line(s)" >&2
  return 0
}

if [[ -f .env ]]; then
  load_env .env
fi
export AWS_REGION="${AWS_REGION_NAME:-us-east-1}"

# Fail with something actionable rather than an opaque auth error. A typo'd
# variable name in .env looks exactly like a missing credential from here.
if [[ -z "${AWS_BEARER_TOKEN_BEDROCK:-}" && -z "${AWS_ACCESS_KEY_ID:-}" ]]; then
  echo "No Bedrock credential found." >&2
  echo "Expected AWS_BEARER_TOKEN_BEDROCK=ABSK... in .env -- check the spelling" >&2
  echo "of the variable name, and that the line is not left over empty from" >&2
  echo ".env.example. Scan your card again at http://localhost:4321/creds" >&2
  exit 1
elif [[ -n "${AWS_BEARER_TOKEN_BEDROCK:-}" && "${AWS_BEARER_TOKEN_BEDROCK}" != ABSK* ]]; then
  echo "AWS_BEARER_TOKEN_BEDROCK does not look like a Bedrock API key (expected" >&2
  echo "it to start with ABSK). Re-scan your card, or check for a stray character." >&2
  exit 1
fi

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
