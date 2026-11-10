#!/usr/bin/env python3
"""Resolve focus targets to channels using recent airodump summary CSVs.

Reads a targets file (lines: "bssid <MAC>" or "ssid <NAME>") and the capture
sessions' summary CSVs, and prints:
    chan <n>          one per resolved channel (deduped)
    pending <target>  for a target not seen in any CSV yet
Listen-only: this only reads already-captured survey data.
"""
import os
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/capture"
TARGETS = sys.argv[2] if len(sys.argv) > 2 else "/run/capture/focus-targets"


def load_targets():
    bssids, ssids = set(), set()
    try:
        with open(TARGETS) as f:
            for line in f:
                kind, _, val = line.strip().partition(" ")
                val = val.strip()
                if kind == "bssid" and val:
                    bssids.add(val.upper())
                elif kind == "ssid" and val:
                    ssids.add(val)
    except OSError:
        pass
    return bssids, ssids


def ap_rows():
    try:
        sessions = sorted(os.listdir(BASE), reverse=True)
    except OSError:
        return
    for name in sessions[:12]:
        path = os.path.join(BASE, name, "summary-01.csv")
        try:
            if os.path.getsize(path) > 8_000_000:
                continue
            with open(path, errors="replace") as f:
                section = None
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    if line.startswith("BSSID,"):
                        section = "ap"
                        continue
                    if line.startswith("Station MAC,"):
                        section = None
                        continue
                    if section != "ap":
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 14:
                        bssid = parts[0].upper()
                        try:
                            chan = int(parts[3])
                        except ValueError:
                            continue
                        # ESSID is second-to-last field; last is Key. ESSID may
                        # itself contain commas, so join everything between.
                        essid = ",".join(parts[13:-1]).strip().replace("\x00", "") if len(parts) >= 15 else parts[13]
                        if chan > 0:
                            yield bssid, chan, essid
        except OSError:
            continue


def main():
    bssids, ssids = load_targets()
    if not bssids and not ssids:
        return
    channels = set()
    seen_bssid, seen_ssid = set(), set()
    for bssid, chan, essid in ap_rows():
        if bssid in bssids:
            channels.add(chan)
            seen_bssid.add(bssid)
        if essid and essid in ssids:
            channels.add(chan)
            seen_ssid.add(essid)
    for c in sorted(channels):
        print("chan", c)
    for b in sorted(bssids - seen_bssid):
        print("pending", "bssid", b)
    for s in sorted(ssids - seen_ssid):
        print("pending", "ssid", s)


if __name__ == "__main__":
    main()
