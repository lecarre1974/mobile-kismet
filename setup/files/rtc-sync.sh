#!/bin/bash
# Sets the system clock from the PiSugar RTC so pcap timestamps are right with no network.
send() {
    exec 3<>/dev/tcp/127.0.0.1/8423 || return 1
    printf '%s\n' "$1" >&3
    timeout 3 head -1 <&3
    exec 3>&-
}

for _ in $(seq 1 30); do
    if send "get rtc_time" >/dev/null 2>&1; then
        send "rtc_rtc2pi"
        date
        exit 0
    fi
    sleep 1
done
echo "PiSugar server not reachable; leaving clock unchanged" >&2
exit 0
