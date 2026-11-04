#!/usr/bin/env bash
# ==============================================================================
# DuckDNS Dynamic DNS Updater for Financial Nifty RAG
# Domain: financial-nifty-rag.duckdns.org
# ==============================================================================

# Replace with your DuckDNS token from https://www.duckdns.org
DUCKDNS_DOMAIN="financial-nifty-rag"
DUCKDNS_TOKEN="${DUCKDNS_TOKEN:-your-duckdns-token-here}"

LOG_FILE="/var/log/duckdns.log"
DATE_STR=$(date -u +"%Y-%m-%d %H:%M:%S UTC")

if [ "$DUCKDNS_TOKEN" = "your-duckdns-token-here" ]; then
    echo "[$DATE_STR] [ERROR] Please set your DUCKDNS_TOKEN in the environment or update this script." | tee -a "$LOG_FILE"
    exit 1
fi

RESPONSE=$(curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=")

if [ "$RESPONSE" = "OK" ]; then
    echo "[$DATE_STR] [SUCCESS] Updated ${DUCKDNS_DOMAIN}.duckdns.org: OK" >> "$LOG_FILE"
else
    echo "[$DATE_STR] [FAILED] DuckDNS update failed. Response: ${RESPONSE}" >> "$LOG_FILE"
fi
