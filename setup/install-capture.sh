#!/bin/bash
# Installs the capture system on a Pi. Run as root from a directory containing files/.
# Usage: install-capture.sh <check-in-SSID> <check-in-password> [dev-home-wifi-connection]
# The third argument is for setup only: check-in returns to that network when it ends.
set -eu
SSID=$1
PSK=$2
DEV_CONN=${3:-}
SRC=$(cd "$(dirname "$0")" && pwd)/files

install -m 755 "$SRC/wifi-capture.sh"   /usr/local/bin/wifi-capture.sh
install -m 755 "$SRC/led-update"        /usr/local/bin/led-update
install -m 755 "$SRC/checkin-toggle.sh" /usr/local/bin/checkin-toggle.sh
install -m 755 "$SRC/rtc-sync.sh"       /usr/local/bin/rtc-sync.sh
install -m 755 "$SRC/focus-control.sh"  /usr/local/bin/focus-control.sh
install -m 755 "$SRC/focus-resolve.py"  /usr/local/bin/focus-resolve.py
install -m 755 "$SRC/capture-status.py" /usr/local/bin/capture-status.py
install -d -m 755 /etc/capture

if [ -n "$DEV_CONN" ]; then
    printf '%s\n' "$DEV_CONN" > /etc/capture/dev-home-wifi
else
    rm -f /etc/capture/dev-home-wifi
fi

cat > /etc/systemd/system/rtc-sync.service <<'EOF'
[Unit]
Description=Set system clock from PiSugar RTC
After=pisugar-server.service
Wants=pisugar-server.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/rtc-sync.sh

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/wifi-capture.service <<'EOF'
[Unit]
Description=Passive all-band Wi-Fi capture
After=local-fs.target rtc-sync.service
Wants=rtc-sync.service
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/usr/local/bin/wifi-capture.sh
ExecStopPost=/usr/local/bin/led-update
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/capture-status.service <<'EOF'
[Unit]
Description=Capture status page (check-in only)

[Service]
Type=simple
User=user
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/usr/bin/python3 -I /usr/local/bin/capture-status.py
Restart=on-failure
RestartSec=3
EOF

# Check-in network: hostapd with plain WPA2-PSK/CCMP. NetworkManager's AP mode
# advertised WPA-PSK-SHA256 as well, and phones could not join the built-in radio.
rm -f /etc/NetworkManager/system-connections/checkin-ap.nmconnection
nmcli connection reload
systemctl mask hostapd.service >/dev/null 2>&1 || true
umask 077
cat > /etc/capture/hostapd.conf <<EOF
driver=nl80211
ssid=$SSID
country_code=US
hw_mode=g
channel=6
ieee80211n=1
wmm_enabled=1
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
rsn_pairwise=CCMP
ieee80211w=0
wpa_passphrase=$PSK
ctrl_interface=/run/hostapd
EOF
umask 022

# The status page (runs as user) may run exactly these actions as root.
cat > /etc/sudoers.d/080-capture-page <<'EOF'
user ALL=(root) NOPASSWD: /usr/bin/systemctl start wifi-capture.service, /usr/bin/systemctl stop wifi-capture.service, /usr/local/bin/checkin-toggle.sh off-async, /usr/local/bin/checkin-toggle.sh extend, /usr/local/bin/focus-control.sh set, /usr/local/bin/focus-control.sh clear
EOF
chmod 440 /etc/sudoers.d/080-capture-page
visudo -cf /etc/sudoers.d/080-capture-page >/dev/null || { rm -f /etc/sudoers.d/080-capture-page; echo "sudoers rule invalid" >&2; exit 1; }

python3 -I - <<'EOF'
import json
p = "/etc/pisugar-server/config.json"
with open(p) as f:
    c = json.load(f)
c["double_tap_enable"] = True
c["double_tap_shell"] = "/usr/local/bin/checkin-toggle.sh toggle"
with open(p, "w") as f:
    json.dump(c, f, indent=4)
EOF

systemctl daemon-reload
systemctl restart pisugar-server.service
systemctl enable rtc-sync.service wifi-capture.service
echo "installed"
