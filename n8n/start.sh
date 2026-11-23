#!/bin/sh
# Import + activate the workflow on every start (idempotent), then run n8n.
set -e
n8n import:workflow --input=/workflows/voice_alert.json
n8n update:workflow --id=fleetVoiceAlert1 --active=true || n8n publish:workflow --id=fleetVoiceAlert1 || true
exec n8n start
