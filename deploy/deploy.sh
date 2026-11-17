#!/bin/bash
# Server-side deploy: unpack /opt/nigoh/nigoh.tgz into /opt/nigoh/src, rebuild, restart. Data volumes are kept.
set -e
cd /opt/nigoh
rm -rf src.new && mkdir src.new && tar xzf nigoh.tgz -C src.new
rm -rf src.old && mv src src.old && mv src.new/nigoh src && rmdir src.new
[ -d src.old/.git ] && mv src.old/.git src/.git || true
cp "/opt/nigoh/dl/Maternal Health Risk Data Set.csv" src/app/maternal_health_risk.csv 2>/dev/null || true
ln -sf /opt/nigoh/.env src/.env
cd src && docker compose build -q && docker compose up -d
for i in $(seq 1 40); do curl -s -m 3 http://127.0.0.1:18700/api/health | grep -q ok && break; sleep 2; done
curl -s -m 5 http://127.0.0.1:18700/api/health
