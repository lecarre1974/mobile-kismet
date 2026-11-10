#!/bin/bash
# Final hardening before handoff. Run as root ON the Pi, last of all.
# After this the unit is silent at boot and reachable only through a check-in.
# Usage: finalize-unit.sh <new-login-password>
set -eu
NEWPW=$1
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
# Run detached (systemd-run): removing networks cuts the SSH session that started it.
exec >/boot/firmware/finalize.log 2>&1
date

echo "== stop capture and clear test data =="
systemctl stop wifi-capture.service capture-status.service 2>/dev/null || true
rm -rf /var/lib/capture/*

echo "== radios: built-in Wi-Fi only during check-in, no Bluetooth =="
cat > /etc/modprobe.d/capture-silent.conf <<'EOF'
# Built-in Wi-Fi loads only during a check-in (checkin-toggle.sh). No Bluetooth.
blacklist brcmfmac
blacklist btusb
blacklist btbcm
blacklist hci_uart
EOF
grep -q '^dtoverlay=disable-bt$' /boot/firmware/config.txt || printf '\n[all]\ndtoverlay=disable-bt\n' >> /boot/firmware/config.txt
systemctl disable --now bluetooth.service 2>/dev/null || true
systemctl mask bluetooth.service
# NetworkManager must never touch either radio (no scanning or probe requests).
printf '[keyfile]\nunmanaged-devices=driver:mt7921u;driver:brcmfmac\n' \
    > /etc/NetworkManager/conf.d/90-capture-adapter-unmanaged.conf

echo "== remove setup-only access =="
rm -f /etc/capture/dev-home-wifi
systemctl disable usb0-up.service boot-diag.service 2>/dev/null || true
rm -f /etc/systemd/system/usb0-up.service /etc/systemd/system/boot-diag.service \
      /usr/local/bin/boot-diag.sh /etc/udev/rules.d/90-usb0-nm-managed.rules
rm -f /boot/firmware/boot-diag.log /boot/firmware/usb-net-setup.log /boot/firmware/pi-setup2.log
rm -f /etc/sudoers.d/090-kismet-setup-temp
UHOME=$(getent passwd user | cut -d: -f6)
if [ -f "$UHOME/.ssh/authorized_keys" ]; then
    sed -i '/kismet-setup-temp/d' "$UHOME/.ssh/authorized_keys"
    [ -s "$UHOME/.ssh/authorized_keys" ] || rm -f "$UHOME/.ssh/authorized_keys"
fi
rm -f /root/silent-test.sh /var/log/silent-test.log "$UHOME/.bash_history" /root/.bash_history

echo "== services not needed headless =="
systemctl disable cups.service cups-browsed.service 2>/dev/null || true

echo "== login password =="
echo "user:$NEWPW" | chpasswd

echo "== clear logs =="
: > /var/log/checkin.log
journalctl --rotate >/dev/null 2>&1 || true
journalctl --vacuum-time=1s >/dev/null 2>&1 || true

echo "== remove saved networks (this ends any SSH session) =="
nmcli -t -f UUID,TYPE connection show | while IFS=: read -r uuid type; do
    [ "$type" = loopback ] || nmcli connection delete uuid "$uuid" || true
done
rm -f /etc/NetworkManager/system-connections/*
rm -f /var/lib/NetworkManager/*.lease /var/lib/NetworkManager/timestamps /var/lib/NetworkManager/seen-bssids

systemctl daemon-reload

echo "== verification =="
echo "blacklist: $(grep -c '^blacklist' /etc/modprobe.d/capture-silent.conf) entries"
echo "disable-bt: $(grep -c '^dtoverlay=disable-bt$' /boot/firmware/config.txt)"
echo "bluetooth: $(systemctl is-enabled bluetooth.service 2>&1)"
echo "NM unmanaged: $(cat /etc/NetworkManager/conf.d/90-capture-adapter-unmanaged.conf | tail -1)"
echo "saved networks: $(ls /etc/NetworkManager/system-connections | wc -l)"
echo "dev flag present: $([ -e /etc/capture/dev-home-wifi ] && echo yes || echo no)"
echo "temp sudoers present: $([ -e /etc/sudoers.d/090-kismet-setup-temp ] && echo yes || echo no)"
echo "temp ssh key present: $(grep -c kismet-setup-temp "$UHOME/.ssh/authorized_keys" 2>/dev/null || echo 0)"
echo "capture enabled at boot: $(systemctl is-enabled wifi-capture.service)"
echo "rtc sync enabled: $(systemctl is-enabled rtc-sync.service)"
echo "pisugar double tap: $(grep -c 'checkin-toggle.sh toggle' /etc/pisugar-server/config.json)"
echo "default target: $(systemctl get-default)"
echo "capture data left: $(find /var/lib/capture -type f | wc -l) files"
sync
echo "finalized; powering off"
systemd-run --on-active=3 --collect /usr/sbin/poweroff >/dev/null
