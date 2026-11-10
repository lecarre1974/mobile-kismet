# mobile-kismet

Headless, battery-powered passive Wi-Fi survey units built on a Raspberry Pi. Power one on and it records Wi-Fi across 2.4, 5 and 6 GHz to standard pcap files, with no screen, login or network needed. A phone-friendly status page is available on demand. The unit is **silent by default** — it only transmits when you deliberately start a check-in.

> Passive capture only (airodump-ng + tcpdump in monitor mode). No injection, deauth, or cracking. Use only on networks you are authorized to assess.

## Hardware (first unit)

- Raspberry Pi Zero W (original, ARMv6) — Raspbian 13 (trixie), 32-bit armhf
- PiSugar 3 battery board (RTC + button + power)
- Alfa AWUS036AXML USB Wi-Fi adapter (MediaTek mt7921u, monitor mode) via micro-USB OTG

Kismet has no 32-bit package, so capture uses **airodump-ng + tcpdump**. A Pi Zero 2 W on 64-bit OS could run Kismet proper; see `memory` notes in the repo history.

## How it works

- **Capture** (`wifi-capture.service` → `wifi-capture.sh`): auto-starts at boot and restarts on failure. airodump-ng hops channels and writes a summary CSV; tcpdump writes full frames (with radiotap) to pcap files that rotate every 5 minutes, into `/var/lib/capture/<session>/`.
- **Focus** (`focus-control.sh`, `focus-resolve.py`): restrict hopping to the channels of chosen SSIDs/BSSIDs so the radio dwells on them. Targets live in tmpfs, so a power-cycle returns to all-channel scanning.
- **Check-in** (`checkin-toggle.sh`, PiSugar double-tap): brings up the built-in radio as a WPA2 hotspot (`hostapd` + `dnsmasq`, random MAC, `10.42.0.1`) and the status page, for 10 minutes. This is the only time the unit transmits.
- **Status page** (`capture-status.py`): served on ports 80 and 8080 so plain `http://10.42.0.1` works. Shows live stats, survey tables, charts; controls for Start/Stop, Focus, and file/session delete; file and whole-session downloads.
- **Status light** (`led-update`, the Pi's green LED): heartbeat = capturing fine; SOS (morse) = capturing but needs attention (low battery / low disk); rapid blink = check-in on / transmitting; solid = not capturing.
- **Clock** (`rtc-sync.sh`): system time comes from the PiSugar RTC, so pcap timestamps are correct with no network (UTC).
- **Silent by default:** the built-in Wi-Fi and Bluetooth drivers are blacklisted and only loaded during a check-in.

## Repo layout

```
setup/
  files/               installed onto the Pi at /usr/local/bin
    wifi-capture.sh     capture supervisor (airodump + tcpdump, focus-aware)
    focus-control.sh    set/clear focus targets, restart capture
    focus-resolve.py    map target SSIDs/BSSIDs -> channels from survey CSVs
    capture-status.py   status page + JSON API + controls (runs during check-in)
    checkin-toggle.sh   bring the check-in hotspot up/down
    led-update          status light patterns
    rtc-sync.sh         set clock from PiSugar RTC
  install-capture.sh   install everything on a fresh card (run on the Pi)
  finalize-unit.sh     harden + wipe + set password + power off, before handoff
  apply-update.sh      one-shot that installs an update at boot (finalized units)
  stage-update-to-sd.sh  (macOS) stage an update onto a finalized unit's SD card
  templates/           credential + guide templates (no real secrets)
  units/               per-unit secrets + filled guides  (gitignored)
```

## Build a unit from a fresh card

1. Flash Raspberry Pi OS (32-bit for Pi Zero W). Note the root partition PARTUUID.
2. On the boot (FAT) partition enable USB gadget networking, or just set up Wi-Fi + SSH with Raspberry Pi Imager and skip USB. (The first unit used a boot-partition one-shot because Imager settings didn't apply — don't assume they did; verify hostname/user/ssh.)
3. Boot, get a shell, then copy `setup/` over and run on the Pi:
   ```
   sudo bash setup/install-capture.sh "<check-in SSID>" "<check-in password>" ["<your home wifi name, setup only>"]
   ```
   This installs the services, the check-in hotspot (hostapd WPA2), the PiSugar double-tap action, and the RTC clock sync.
4. Test capture, check-in, and the status page.
5. Before handoff:
   ```
   sudo bash setup/finalize-unit.sh "<new login password>"
   ```
   Wipes test captures, blacklists the radios (silent at boot), removes setup-only access (home Wi-Fi, temporary SSH key, temporary sudo), sets the login password, and powers off.

## Update a finalized unit

A finalized unit is reachable only over its own check-in network, and macOS can't write the Linux partition, so updates go through the boot partition:

1. Power the Pi off, put its SD card in a Mac.
2. `bash setup/stage-update-to-sd.sh` — copies the updated `files/` and `apply-update.sh` onto the boot partition and adds a one-time boot hook. It backs up `cmdline.txt` and refuses on the wrong card.
3. Card back in the Pi, power on. It installs the update, reboots clean, and writes `/boot/firmware/focus-install.log` (readable from the Mac next time).

## Per-unit credentials

Each unit has its own SSID, check-in password, and login password. **These are not in git.** Keep the real values in a password manager. `setup/templates/` has placeholder copies of the unit record and the client guide; fill a copy per unit under `setup/units/` (gitignored).

## Field reference

The client-facing one-pager (buttons, light patterns, check-in, Focus, Delete, SFTP) is generated per unit from `setup/templates/unit-guide-template.md`.
