# Wi-Fi Capture Unit: Quick Guide

This unit records Wi-Fi traffic on 2.4, 5 and 6 GHz to standard pcap files. It starts recording by itself every time it is powered on. While recording it only listens and does not transmit, unless you turn on a check-in.

## Buttons (PiSugar battery board)

| What you want | What to do |
|---|---|
| **Power on** | **Button above the HDMI port:** short click, then a long click. |
| **Power off** | **Button above the HDMI port:** press and hold. |
| **Check-in on / off** | **Button next to the USB port:** double tap *once* (two quick taps, like double-clicking a mouse), then wait 30 seconds. Don't keep tapping, because extra taps switch it back. |

## Status light (green light on the Pi)

| Light | Meaning |
|---|---|
| **Heartbeat** (slow double pulse) | Recording silently. All good. |
| **SOS in Morse** (... --- ...) | Recording, but needs attention: battery under 20%, or SD card nearly full. |
| **Rapid blink** | Check-in is on. **The unit is transmitting.** |
| **Solid on** | Not recording. It may still be starting (allow 4 minutes after power-on), capture was stopped from the status page, or the Wi-Fi adapter is unplugged. Power-cycling restarts recording. |

## Check-in: see status and get files

A check-in turns on a small Wi-Fi network so you can view the unit from a phone or laptop. **While it's on, the unit is visible to anyone scanning.** It switches itself off after 10 minutes. You can also end it with another double tap, or with the button on the page.

1. Double tap the button next to the USB port once, and wait about 30 seconds for the light to blink rapidly.
2. Join the Wi-Fi network:
   - **Network:** `<CHECK-IN-SSID>`
   - **Password:** `<CHECK-IN-PASSWORD>`
   - The phone may say "no internet". Choose to stay connected, and turn off mobile data and any VPN.
3. Open **`10.42.0.1`** in the browser. If it doesn't load, type `http://10.42.0.1`. Bookmark it.

**On the page:** recording status, live packet rate, networks and devices seen, channel and encryption charts, battery, SD card space, and **Start/Stop capture**. A stop lasts until you press Start or power-cycle the unit. You can download single files or a whole session (`.tar`).

**Focus on specific networks.** By default the unit hops every channel and sees everything. To concentrate on chosen networks so the radio dwells on them:

- In the **Networks** table, tick one or more rows, then press **Focus on selected**; or
- Under **Focus**, pick SSID or BSSID, type the name or MAC, and press **Add to focus**.

The unit then hops only those networks' channels and starts a new `focus-...` session, which captures far more of their traffic. A target not yet seen stays pending, and focus locks on automatically once it appears. Press **Back to all channels** to undo it. A power-cycle always returns to all channels. Focus still only listens.

**Delete files.** Each file has a **Delete** button, and each session a **Delete session** button (the one currently recording can't be deleted). Deletes are permanent.

**Large downloads:** SFTP is faster than the browser, for example with FileZilla, Cyberduck or WinSCP.

| Setting | Value |
|---|---|
| Host | `10.42.0.1` |
| Port | 22 |
| Username | `user` |
| Password | `<LOGIN-PASSWORD>` |

Files are in `/var/lib/capture/`, with one folder per recording session named by start time (UTC):

- `cap-YYYYMMDD-HHMMSS.pcap`: full packets with radio details (channel, signal strength). A new file starts every 5 minutes. Open them in Wireshark.
- `summary-01.csv`: airodump-ng summary of networks and devices.

Delete old sessions over SFTP when you no longer need them.

## Good to know

- **Channels covered:** 2.4 GHz channels 1–11, all of 5 GHz, and 6 GHz (98 channels, US rules). Channels 12–14 are not available.
- **Hopping:** there is one radio, so it hops between channels and listens to each one in turn. Short bursts on a channel can be missed.
- **Timestamps:** they come from the battery board's clock, in UTC, so no network is needed.
- **Charging:** use the PiSugar's USB-C port. The unit keeps recording while charging.
- **Power off:** holding the power button cuts power immediately. Recording saves continuously, so at most the last few seconds are lost.
- **Keep the Wi-Fi adapter plugged in.** Without it the light goes solid and nothing is recorded.
