#!/usr/bin/env bash
# Show exactly what one attendee's Bedrock key can do.
#
#   ./show-seat-perms.sh tmws-07
#
# There is no "describe this bearer token's permissions" API: the token belongs
# to an IAM user, so the answer is that user's policies, which is what this
# prints -- then simulates representative actions to show allow/deny for real
# rather than by reading JSON.
set -euo pipefail
USER_NAME=${1:?usage: show-seat-perms.sh <iam-user>}
. "$(dirname "${0}")/_preflight.sh"
export AWS_REGION=${AWS_REGION:-us-east-1}

echo "== Bedrock credentials held by ${USER_NAME}"
aws iam list-service-specific-credentials --user-name "${USER_NAME}" \
  --service-name bedrock.amazonaws.com \
  --query 'ServiceSpecificCredentials[].{alias:ServiceCredentialAlias,id:ServiceSpecificCredentialId,status:Status,expires:ExpirationDate}' \
  --output table

echo "== groups and policies"
aws iam list-groups-for-user --user-name "${USER_NAME}" --query 'Groups[].GroupName' --output text
aws iam list-attached-user-policies --user-name "${USER_NAME}" --query 'AttachedPolicies[].PolicyName' --output text

echo
ACCT=${ACCOUNT}
WHEN=${WHEN:-$(python3 -c "from datetime import datetime,timezone;print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")}
echo "== simulated decisions at ${WHEN} (override with WHEN=2026-10-08T12:00:00Z)"
printf '  %-46s %s\n' "ACTION / RESOURCE" "DECISION"
sim() {  # sim <action> <resource> <label>
  d=$(aws iam simulate-principal-policy \
        --policy-source-arn "arn:aws:iam::${ACCT}:user/${USER_NAME}" \
        --action-names "${1}" --resource-arns "${2}" \
        --context-entries "ContextKeyName=aws:CurrentTime,ContextKeyType=date,ContextKeyValues=${WHEN}" \
        --query 'EvaluationResults[0].EvalDecision' --output text 2>/dev/null || echo "error")
  printf '  %-46s %s\n' "${3}" "${d}"
}
sim bedrock:InvokeModel "arn:aws:bedrock:us-east-1:${ACCT}:inference-profile/us.anthropic.claude-sonnet-5" "bedrock:InvokeModel  (workshop model)"
sim bedrock:InvokeModel "arn:aws:bedrock:us-east-1::foundation-model/meta.llama3-70b-instruct-v1:0"      "bedrock:InvokeModel  (non-workshop model)"
sim bedrock:CallWithBearerToken "*"        "bedrock:CallWithBearerToken"
sim s3:ListBucket "arn:aws:s3:::any-bucket" "s3:ListBucket"
sim iam:CreateUser "arn:aws:iam::${ACCT}:user/x" "iam:CreateUser"
sim sts:GetCallerIdentity "*"              "sts:GetCallerIdentity"
echo
echo "Note: a bedrock.amazonaws.com service-specific credential is refused by"
echo "every other AWS service regardless of policy -- the s3/iam rows above are"
echo "what the USER could do with an access key, not what this token can do."
