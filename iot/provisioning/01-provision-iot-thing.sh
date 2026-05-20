#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# 01-provision-iot-thing.sh
# Creates an AWS IoT Core Thing, certificates, and policy for the Zumi.
# Outputs everything into a local staging directory ready for deployment.
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

THING_NAME="${1:-robolink-zumi}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STAGE_DIR="${SCRIPT_DIR}/staging/${THING_NAME}"
CERT_DIR="${STAGE_DIR}/certs"
POLICY_NAME="${THING_NAME}-policy"

echo "==> Provisioning IoT Thing: ${THING_NAME} in ${REGION}"

# ── Create staging dirs ───────────────────────────────────────────────────
mkdir -p "${CERT_DIR}"

# ── 1. Create the Thing (idempotent) ─────────────────────────────────────
if aws iot describe-thing --thing-name "${THING_NAME}" --region "${REGION}" >/dev/null 2>&1; then
    echo "    Thing '${THING_NAME}' already exists — skipping creation."
else
    aws iot create-thing --thing-name "${THING_NAME}" --region "${REGION}"
    echo "    Created thing '${THING_NAME}'."
fi

# ── 2. Create keys & certificate ─────────────────────────────────────────
echo "==> Creating certificate and keys..."
CERT_OUTPUT=$(aws iot create-keys-and-certificate \
    --set-as-active \
    --region "${REGION}" \
    --output json)

CERT_ARN=$(echo "${CERT_OUTPUT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['certificateArn'])")
CERT_ID=$(echo "${CERT_OUTPUT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['certificateId'])")

echo "${CERT_OUTPUT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['certificatePem'])" \
    > "${CERT_DIR}/device-certificate.pem.crt"
echo "${CERT_OUTPUT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['keyPair']['PrivateKey'])" \
    > "${CERT_DIR}/private.pem.key"
echo "${CERT_OUTPUT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['keyPair']['PublicKey'])" \
    > "${CERT_DIR}/public.pem.key"

echo "    Certificate ID: ${CERT_ID}"

# ── 3. Download Amazon Root CA ────────────────────────────────────────────
echo "==> Downloading Amazon Root CA..."
curl -sS -o "${CERT_DIR}/AmazonRootCA1.pem" \
    "https://www.amazontrust.com/repository/AmazonRootCA1.pem"

# ── 4. Create IoT policy (idempotent) ────────────────────────────────────
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "iot:Connect",
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:client/${THING_NAME}"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:topic/zumi/${THING_NAME}/*"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Subscribe",
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:topicfilter/zumi/${THING_NAME}/*"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Receive",
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:topic/zumi/${THING_NAME}/*"
    }
  ]
}
EOF
)

if aws iot get-policy --policy-name "${POLICY_NAME}" --region "${REGION}" >/dev/null 2>&1; then
    echo "    Policy '${POLICY_NAME}' already exists — skipping creation."
else
    aws iot create-policy \
        --policy-name "${POLICY_NAME}" \
        --policy-document "${POLICY_DOC}" \
        --region "${REGION}"
    echo "    Created policy '${POLICY_NAME}'."
fi

# ── 5. Attach policy to certificate ──────────────────────────────────────
echo "==> Attaching policy to certificate..."
aws iot attach-policy \
    --policy-name "${POLICY_NAME}" \
    --target "${CERT_ARN}" \
    --region "${REGION}" 2>/dev/null || true

# ── 6. Attach certificate to thing ───────────────────────────────────────
echo "==> Attaching certificate to thing..."
aws iot attach-thing-principal \
    --thing-name "${THING_NAME}" \
    --principal "${CERT_ARN}" \
    --region "${REGION}" 2>/dev/null || true

# ── 7. Get IoT endpoint and write config.json ────────────────────────────
ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --region "${REGION}" --query endpointAddress --output text)

cat > "${STAGE_DIR}/config.json" <<EOF
{
  "endpoint": "${ENDPOINT}",
  "thing_name": "${THING_NAME}",
  "cert_dir": "certs",
  "cert_file": "device-certificate.pem.crt",
  "key_file": "private.pem.key",
  "root_ca_file": "AmazonRootCA1.pem",
  "telemetry_interval_sec": 5
}
EOF

echo ""
echo "==> Provisioning complete!"
echo "    Staging directory : ${STAGE_DIR}"
echo "    Endpoint          : ${ENDPOINT}"
echo "    Thing             : ${THING_NAME}"
echo "    Certificate ARN   : ${CERT_ARN}"
echo "    Policy            : ${POLICY_NAME}"
