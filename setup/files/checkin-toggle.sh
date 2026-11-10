#!/bin/bash
# Turns the check-in Wi-Fi network and status page on or off.
# Usage: checkin-toggle.sh [toggle|on|off]   (PiSugar double tap runs "toggle")
# Uses hostapd + dnsmasq directly on the built-in radio (plain WPA2-PSK/CCMP).
# Capture keeps running either way. Check-in switches itself off after AUTO_OFF_SECS.
set -u
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

STATE=/run/checkin
AUTO_OFF_SECS=600
HOSTAPD_CONF=/etc/capture/hostapd.conf
AP_ADDR=10.42.0.1/24
DEV_FLAG=/etc/capture/dev-home-wifi   # holds a connection name during setup only

mkdir -p "$STATE"
exec >>/var/log/checkin.log 2>&1
echo "$(date '+%F %T') checkin ${1:-toggle}"

exec 9>"$STATE/lock"
if [ "${1:-toggle}" = toggle ]; then
    # Button presses: ignore while busy and for a few seconds after a change,
    # so repeated taps cannot queue up and flip the state back.
    flock -n 9 || { echo "busy, ignoring tap"; exit 0; }
    last=$(cat "$STATE/last_change" 2>/dev/null || echo 0)
    if [ $(( $(date +%s) - last )) -lt 8 ]; then
        echo "tap too soon after last change, ignoring"
        exit 0
    fi
else
    flock -w 30 9 || { echo "busy, ignoring"; exit 0; }
fi

builtin_iface() {
    local i d
    for i in /sys/class/net/*; do
        d=$(readlink "$i/device/driver" 2>/dev/null) || continue
        if [ "$(basename "$d")" = brcmfmac ]; then
            basename "$i"
            return 0
        fi
    done
    return 1
}

random_mac() {
    # Locally administered, unicast: hides the Raspberry Pi vendor prefix.
    printf '%02x:%02x:%02x:%02x:%02x:%02x\n' \
        $(( ( $(od -An -N1 -tu1 /dev/urandom) & 0xfc ) | 0x02 )) \
        $(od -An -N5 -tu1 /dev/urandom)
}

# hostapd and dnsmasq run as their own transient units so they outlive whoever
# called this script (systemd kills a finished caller's whole process group).
stop_daemons() {
    systemctl stop checkin-hostapd.service checkin-dnsmasq.service 2>/dev/null
    systemctl reset-failed checkin-hostapd.service checkin-dnsmasq.service 2>/dev/null
    sleep 1
}

release_radio() {
    local w=$1
    ip addr flush dev "$w" 2>/dev/null
    ip link set "$w" down 2>/dev/null
    if [ -f "$STATE/orig_mac" ]; then
        ip link set "$w" address "$(cat "$STATE/orig_mac")" 2>/dev/null
        rm -f "$STATE/orig_mac"
    fi
    if [ -f "$DEV_FLAG" ]; then
        nmcli device set "$w" managed yes
        sleep 2
        nmcli connection up "$(cat "$DEV_FLAG")"
    else
        unload_driver
    fi
}

unload_driver() {
    # Vendor helper modules hold a reference to brcmfmac; remove them first.
    local m
    for m in brcmfmac_cyw brcmfmac_wcc brcmfmac_bca; do
        grep -q "^$m " /proc/modules && rmmod "$m"
    done
    modprobe -r brcmfmac || echo "WARNING: built-in Wi-Fi driver still loaded (interface left down)"
}

turn_on() {
    [ -e "$STATE/active" ] && return 0
    modprobe brcmfmac
    local n=0 w=""
    until w=$(builtin_iface); do
        n=$((n + 1))
        [ "$n" -gt 30 ] && { echo "built-in Wi-Fi did not appear"; [ -f "$DEV_FLAG" ] || unload_driver; return 1; }
        sleep 1
    done
    rfkill unblock wifi
    nmcli device set "$w" managed no 2>/dev/null
    sleep 1
    ip link set "$w" down
    cat "/sys/class/net/$w/address" > "$STATE/orig_mac"
    ip link set "$w" address "$(random_mac)" || echo "could not randomize MAC, using hardware address"
    ip addr flush dev "$w"
    ip link set "$w" up
    ip addr add "$AP_ADDR" dev "$w"

    stop_daemons
    : > "$STATE/hostapd.log"
    systemd-run --unit=checkin-hostapd --collect -p Restart=on-failure \
        hostapd -i "$w" -f "$STATE/hostapd.log" "$HOSTAPD_CONF"
    n=0
    until grep -q 'AP-ENABLED' "$STATE/hostapd.log" 2>/dev/null; do
        n=$((n + 1))
        if [ "$n" -gt 20 ]; then
            echo "hostapd did not start:"; tail -20 "$STATE/hostapd.log"
            stop_daemons; release_radio "$w"
            return 1
        fi
        sleep 1
    done
    systemd-run --unit=checkin-dnsmasq --collect -p Restart=on-failure \
        dnsmasq --keep-in-foreground --conf-file=/dev/null --port=0 \
        --interface="$w" --bind-interfaces \
        --dhcp-range=10.42.0.10,10.42.0.60,255.255.255.0,1h \
        --dhcp-option=3 --dhcp-option=6 \
        --dhcp-leasefile="$STATE/dnsmasq.leases" \
        --log-dhcp --log-facility="$STATE/dnsmasq.log"

    printf '%s\n' "$w" > "$STATE/iface"
    touch "$STATE/active"
    echo $(( $(date +%s) + AUTO_OFF_SECS )) > "$STATE/expires"
    systemctl start capture-status.service
    systemd-run --unit=checkin-autooff --collect --on-active="$AUTO_OFF_SECS" \
        /usr/local/bin/checkin-toggle.sh off
    /usr/local/bin/led-update
    echo "check-in on via $w ($(cat "/sys/class/net/$w/address"))"
}

turn_off() {
    systemctl stop checkin-autooff.timer 2>/dev/null
    systemctl stop capture-status.service
    stop_daemons
    local w
    w=$(cat "$STATE/iface" 2>/dev/null || builtin_iface || true)
    rm -f "$STATE/active" "$STATE/expires" "$STATE/iface"
    [ -n "$w" ] && release_radio "$w"
    /usr/local/bin/led-update
    echo "check-in off"
}

extend() {
    [ -e "$STATE/active" ] || { echo "check-in not active"; return 1; }
    systemctl stop checkin-autooff.timer 2>/dev/null
    systemd-run --unit=checkin-autooff --collect --on-active="$AUTO_OFF_SECS" \
        /usr/local/bin/checkin-toggle.sh off
    echo $(( $(date +%s) + AUTO_OFF_SECS )) > "$STATE/expires"
    echo "check-in extended"
}

case "${1:-toggle}" in
    on)  turn_on ;;
    off) turn_off ;;
    extend) extend ;;
    off-async)
        # From the status page: run "off" outside the page's own service,
        # because turning off stops that service.
        flock -u 9
        systemd-run --unit=checkin-web-off --collect --on-active=2 \
            /usr/local/bin/checkin-toggle.sh off
        ;;
    toggle)
        if [ -e "$STATE/active" ]; then turn_off; else turn_on; fi
        date +%s > "$STATE/last_change"
        ;;
    *) echo "unknown action: $1"; exit 2 ;;
esac
