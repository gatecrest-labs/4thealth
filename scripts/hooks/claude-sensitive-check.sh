#!/usr/bin/env bash
# Claude PreToolUse hook: blocks sensitive strings before Write/Edit tool calls.
# Mirrors the pattern in scripts/check-sensitive-strings.sh — strings are
# base64-encoded so they never appear in plaintext in this repo.
set -euo pipefail

input=$(cat)

t1=$(printf 'eGNlbGVuZXJneQ==' | base64 -d)
t2=$(printf 'eGNlbA==' | base64 -d)

tool=$(printf '%s' "$input" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_name', ''))
" 2>/dev/null || echo "")

case "$tool" in
  Write)
    content=$(printf '%s' "$input" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('content', ''))
" 2>/dev/null || echo "")
    ;;
  Edit)
    content=$(printf '%s' "$input" | python3 -c "
import sys, json
ti = json.load(sys.stdin).get('tool_input', {})
print(ti.get('new_string', ''))
" 2>/dev/null || echo "")
    ;;
  *)
    exit 0
    ;;
esac

if printf '%s' "$content" | grep -qiE "\\b${t2}\\b|${t1}"; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Blocked: the content contains a sensitive string that must not appear in this repository. Remove or redact the flagged reference before writing."}}\n'
fi
