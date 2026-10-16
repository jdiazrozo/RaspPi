#!/bin/sh
# Runs as root from /opt (root-owned), not from the pi-writable git checkout.
set -e
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)"

install -d -m 755 /opt/sentinel/sentinel
rm -rf /opt/sentinel/sentinel/__pycache__
install -m 644 "$SRC"/*.py /opt/sentinel/sentinel/
install -m 644 "$SRC"/sentinel.service /etc/systemd/system/sentinel.service
install -d -m 700 /var/lib/sentinel /etc/sentinel
printf '#!/bin/sh\ncd /opt/sentinel && exec /usr/bin/python3 -m sentinel "$@"\n' > /usr/local/bin/sentinel
chmod 755 /usr/local/bin/sentinel

systemctl daemon-reload
systemctl enable sentinel.service
systemctl restart sentinel.service
systemctl --no-pager status sentinel.service | head -5
