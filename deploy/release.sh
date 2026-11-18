#!/bin/bash
# Выкладка без сборки образа на сервере (почему — см. compose.mount.yml).
#   /opt/nigoh/release.sh /opt/nigoh/<архив>.tgz <sha256>
# Распаковывает архив в /opt/nigoh/src, перезапускает приложение на готовом образе со смонтированным кодом,
# ставит пакеты, которых ещё нет в образе, ждёт /api/health, запускает тесты и проверку входа всех ролей.
# Если приложение не поднялось, возвращает предыдущую версию. Данные (тома) сохраняются.
set -u
ARCHIVE=${1:?archive path}
WANT=${2:?sha256 of the archive}
ROOT=/opt/nigoh
B=http://127.0.0.1:18700
UP="docker compose -f docker-compose.yml -f deploy/compose.mount.yml up -d --no-build --force-recreate"
healthy() { for _ in $(seq 1 "$1"); do curl -fsS -m 3 $B/api/health 2>/dev/null | grep -q ok && return 0; sleep 2; done; return 1; }

cd $ROOT || exit 1
[ "$(sha256sum "$ARCHIVE" | cut -d' ' -f1)" = "$WANT" ] || { echo "__ARCHIVE_MISMATCH"; exit 3; }
tar tzf "$ARCHIVE" | grep -q '^nigoh/deploy/compose.mount.yml$' || { echo "__ARCHIVE_LAYOUT_BAD"; exit 4; }
rm -rf src.new && mkdir src.new && tar xzf "$ARCHIVE" -C src.new || exit 6
rm -rf src.old && mv src src.old && mv src.new/nigoh src && rmdir src.new
[ -d src.old/.git ] && mv src.old/.git src/.git
ln -sf $ROOT/.env src/.env
(cd src && $UP 2>&1 | tail -n 2)
# Пакеты, добавленные в requirements.txt после сборки образа, ставятся в новый контейнер;
# приложение импортирует их при первом обращении, поэтому ждать установки не нужно.
echo "__PACKAGES=$(docker exec -i nigoh-app-1 pip install -q --disable-pip-version-check --root-user-action=ignore -r /srv/requirements.txt < /dev/null 2>&1 | tail -n 1 | cut -c1-160)"

if ! healthy 45; then
  echo "__UNHEALTHY: putting the previous version back"
  docker logs --tail 30 nigoh-app-1 2>&1 | cut -c1-220
  rm -rf src.bad && mv src src.bad && mv src.old src
  [ -d src.bad/.git ] && mv src.bad/.git src/.git
  ln -sf $ROOT/.env src/.env
  if [ -f src/deploy/compose.mount.yml ]; then (cd src && $UP 2>&1 | tail -n 2); else (cd src && docker compose up -d --no-build --force-recreate 2>&1 | tail -n 2); fi
  healthy 30; echo "__ROLLBACK_HEALTH=$(curl -s -m 5 $B/api/health)"
  exit 7
fi

echo "__HEALTH=$(curl -s -m 5 $B/api/health)"
echo "__TESTS=$(docker exec -i nigoh-app-1 pytest -q < /dev/null 2>&1 | tail -n 1)"
PW=$(grep '^DEMO_PASSWORD=' .env | cut -d= -f2-)
J=$(mktemp)
echo "__ANONYMOUS=$(curl -s -o /dev/null -w '%{http_code}' -m 10 $B/api/dashboard)"
for U in rahbar mutaxassis shifokor hamshira; do
  C=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -c "$J" -H 'Content-Type: application/json' -d "{\"username\":\"$U\",\"password\":\"$PW\"}" $B/api/login)
  echo "__SIGN_IN_$U=$C $(curl -s -m 10 -b "$J" $B/api/me | grep -o '"role":"[a-z]*"')"
done
rm -f "$J"
echo "__WRONG_PASSWORD=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H 'Content-Type: application/json' -d '{"username":"rahbar","password":"x"}' $B/api/login)"
docker ps --filter name=nigoh-app-1 --format '{{.Names}} {{.Status}}'
