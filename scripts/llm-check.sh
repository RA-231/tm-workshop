#!/usr/bin/env bash
# Validate your workshop credential BEFORE bringing up LiteLLM/LibreChat.
# Read-only: confirms the key works and lists the models it can reach, then
# checks that the model the docs call `workshop-default` is one of them.
#
#   task llm:check
#
# Pull the credential out of .env without echoing secrets -- and without EXECUTING the
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

API=${LLM_API_BASE:-https://api.openai.com/v1}

if [[ -f .env ]]; then
  load_env .env
fi

# Fail with something actionable rather than an opaque auth error. A typo'd
# variable name in .env looks exactly like a missing credential from here.
if [[ -z "${LLM_API_KEY:-}" ]]; then
  echo "No model credential found." >&2
  echo "Expected LLM_API_KEY=sk-... in .env -- check the spelling of the variable" >&2
  echo "name, and that the line is not left over empty from .env.example." >&2
  echo "Scan your card again at http://localhost:4321/creds" >&2
  exit 1
elif [[ "${LLM_API_KEY}" != sk-* ]]; then
  echo "LLM_API_KEY does not look like an API key (expected it to start with sk-)." >&2
  echo "Re-scan your card, or check for a stray character." >&2
  exit 1
fi

echo "== models your key can reach =="
models=$(curl -sS "${API}/models" -H "Authorization: Bearer ${LLM_API_KEY}")
if printf '%s' "${models}" | grep -q '"error"'; then
  echo "The provider rejected this key:" >&2
  printf '%s' "${models}" | python3 -c 'import json,sys; e=json.load(sys.stdin)["error"]; print("  ", e.get("code"), "-", str(e.get("message"))[:140])' >&2
  echo >&2
  echo "If the workshop has ended, the key has expired -- that is expected." >&2
  exit 1
fi
printf '%s' "${models}" | python3 -c 'import json,sys
ids = sorted(m["id"] for m in json.load(sys.stdin).get("data", []))
for i in ids: print("  ", i)
print(f"  ({len(ids)} models)")'

echo
echo "== the model the docs call workshop-default =="
want="${WORKSHOP_DEFAULT_MODEL#openai/}"
if [[ -z "${want}" ]]; then
  echo "  WORKSHOP_DEFAULT_MODEL is not set in .env -- the workshop-default alias"
  echo "  will not resolve. Set it to one of the models listed above."
  exit 1
fi
if printf '%s' "${models}" | python3 -c 'import json,sys
want = sys.argv[1]
ids = {m["id"] for m in json.load(sys.stdin).get("data", [])}
raise SystemExit(0 if want in ids else 1)' "${want}"; then
  echo "  ok       ${want}"
else
  echo "  MISSING  ${want}   <- not available to this key; pick one from the list above"
  exit 1
fi

echo
echo "Done. Bring the chat stack up with: task up:chat"
