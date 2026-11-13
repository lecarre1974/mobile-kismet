#!/usr/bin/env python3
"""Build the client PDF user guide for one unit.

Usage: python3 make-user-guide.py units/unit-01.txt units/unit-01-user-guide.pdf
Needs reportlab. Credentials come from the unit file (gitignored), never from here.
"""
import sys
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing, Rect, Line, String
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle, KeepTogether, PageBreak)

unit_file, out = sys.argv[1], sys.argv[2]
U = dict(l.strip().split("=", 1) for l in open(unit_file) if "=" in l and not l.startswith("#"))
SSID, PSK, USER, PW = U["SSID"], U["PSK"], U.get("LOGIN_USER", "user"), U["LOGIN_PASSWORD"]
ADDR = "10.42.0.1"

INK = colors.HexColor("#1b2430"); DIM = colors.HexColor("#5b6675"); LINE = colors.HexColor("#d5dbe3")
ACC = colors.HexColor("#1f5fae"); SOFT = colors.HexColor("#eef3f9"); WARN = colors.HexColor("#fff6e0")
WARNLINE = colors.HexColor("#e0b040"); GREEN = colors.HexColor("#22a35a"); OFF = colors.HexColor("#e6e9ee")

base = dict(fontName="Helvetica", fontSize=10, leading=14, textColor=INK, alignment=TA_LEFT)
S = {
    "title": ParagraphStyle("title", **{**base, "fontName": "Helvetica-Bold", "fontSize": 24, "leading": 28}),
    "subtitle": ParagraphStyle("subtitle", **{**base, "fontSize": 11.5, "leading": 16, "textColor": DIM}),
    "h1": ParagraphStyle("h1", **{**base, "fontName": "Helvetica-Bold", "fontSize": 15, "leading": 19,
                                  "textColor": ACC, "spaceBefore": 12, "spaceAfter": 5, "keepWithNext": 1}),
    "h2": ParagraphStyle("h2", **{**base, "fontName": "Helvetica-Bold", "fontSize": 11.5, "leading": 15,
                                  "spaceBefore": 9, "spaceAfter": 3, "keepWithNext": 1}),
    "body": ParagraphStyle("body", **{**base, "spaceAfter": 5}),
    "small": ParagraphStyle("small", **{**base, "fontSize": 8.5, "leading": 11.5, "textColor": DIM}),
    "cell": ParagraphStyle("cell", **{**base, "fontSize": 9.5, "leading": 12.5}),
    "cellb": ParagraphStyle("cellb", **{**base, "fontName": "Helvetica-Bold", "fontSize": 9.5, "leading": 12.5}),
    "step": ParagraphStyle("step", **{**base, "leftIndent": 22, "firstLineIndent": -22, "spaceAfter": 5}),
}
P = lambda t, s="body": Paragraph(t, S[s])
B = lambda t: f'<font name="Helvetica-Bold">{t}</font>'
BTN = lambda t: f'<font name="Helvetica-Bold" color="#1f5fae">[{t}]</font>'
MONO = lambda t: f'<font name="Courier-Bold">{t}</font>'


def steps(items, start=1):
    return [P(f'{B(str(i) + ".")}&nbsp;&nbsp;{t}', "step") for i, t in enumerate(items, start)]


def table(rows, widths, header=True):
    data = [[P(c, "cellb" if (header and r == 0) or (c_i == 0) else "cell") if isinstance(c, str) else c
             for c_i, c in enumerate(row)] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
          ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 1, ACC)]
    t.setStyle(TableStyle(st))
    return t


def box(flows, bg=SOFT, edge=ACC):
    t = Table([[flows]], colWidths=[7.0 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 4, edge),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def light(pattern, w=124, h=16):
    """Draw ~3 seconds of an LED pattern: list of (start_s, length_s) 'on' spans."""
    d = Drawing(w, h + 10)
    scale = w / 3.0
    d.add(Rect(0, 8, w, h, fillColor=OFF, strokeColor=None))
    for s, ln in pattern:
        d.add(Rect(s * scale, 8, max(1.2, ln * scale), h, fillColor=GREEN, strokeColor=None))
    d.add(Line(0, 4, w, 4, strokeColor=LINE, strokeWidth=0.5))
    d.add(String(0, -4, "0 s", fontName="Helvetica", fontSize=6.5, fillColor=DIM))
    d.add(String(w - 10, -4, "3 s", fontName="Helvetica", fontSize=6.5, fillColor=DIM))
    return d


HEARTBEAT = [(t + o, 0.07) for t in (0.0, 1.3, 2.6) for o in (0.0, 0.25) if t + o < 3]
dot, dash, gap = 0.12, 0.36, 0.12
sos, t = [], 0.0
for sym in "...---...":
    ln = dot if sym == "." else dash
    sos.append((t, ln)); t += ln + gap
SOS = [(s * 3.0 / t, ln * 3.0 / t) for s, ln in sos]
RAPID = [(i * 0.1, 0.05) for i in range(30)]
SOLID = [(0, 3.0)]

story = []
# ---------------- Page 1 ----------------
story += [P("Wi-Fi Capture Unit", "title"), Spacer(1, 4),
          P("User guide: buttons, lights, check-in, and the status page", "subtitle"), Spacer(1, 10),
          box([P(f'{B("What it does.")} Records Wi-Fi traffic on 2.4, 5 and 6 GHz to standard pcap files. '
                 f'It starts recording by itself whenever it is powered on. While recording it '
                 f'{B("only listens")} and does not transmit, unless you turn on a check-in.')])]

story += [P("Quick start", "h1")]
story += steps([
    f'{B("Power on:")} on the button above the HDMI port, give a {B("short click, then a long click")}.',
    f'{B("Wait up to 4 minutes")} until the green light shows a {B("heartbeat")} (two quick pulses, pause). '
    f'It is now recording.',
    f'{B("To look at it:")} double tap the button next to the USB port {B("once")}, then wait 30 seconds until the light '
    f'{B("blinks rapidly")}.',
    f'Join Wi-Fi {MONO(SSID)} on your phone, then open {MONO(ADDR)} in the browser.',
    f'{B("When done:")} press {BTN("End check-in now")} on the page. The unit goes silent and keeps recording.',
])

story += [P("Buttons", "h1"),
          table([["What you want", "What to do"],
                 ["Power on", f'{B("Button above the HDMI port:")} short click, then a long click.'],
                 ["Power off", f'{B("Button above the HDMI port:")} press and hold until the light goes out.'],
                 ["Check-in on / off", f'{B("Button next to the USB port:")} double tap {B("once")} (like double-clicking '
                                       f'a mouse), then wait 30 seconds. Do not keep tapping; extra taps switch it back.']],
                [1.6 * inch, 5.4 * inch])]

light_rows = [["Light", "Pattern (3 seconds)", "Meaning"],
              ["Heartbeat", light(HEARTBEAT), "Recording silently. All good."],
              ["SOS", light(SOS), "Recording, but needs attention: battery under 20% (not charging) or SD card nearly full."],
              ["Rapid blink", light(RAPID), f'Check-in is on. {B("The unit is transmitting")} and can be seen by anyone scanning.'],
              ["Solid on", light(SOLID), "Not recording. Still starting (allow 4 minutes), capture was stopped from the page, "
                                         "or the Wi-Fi adapter is unplugged. Power-cycling restarts recording."],
              ["Off", light([]), "Powered off, or the battery is empty."]]
story += [KeepTogether([P("Status light (green light on the Pi)", "h1"),
                        table(light_rows, [1.05 * inch, 2.0 * inch, 3.95 * inch])])]

# ---------------- Check-in ----------------
story += [PageBreak(), P("Check-in: connect to the unit", "h1"),
          P("A check-in turns on a small Wi-Fi network so you can view the unit from a phone or laptop. "
            "It switches itself off after 10 minutes. Recording continues the whole time.")]
story += steps([
    f'Double tap the button next to the USB port {B("once")}.',
    f'Wait about 30 seconds until the green light {B("blinks rapidly")}. Do not join before that.',
    "On your phone or laptop, open Wi-Fi settings and join:",
])
cred = Table([[P(B("Network"), "cell"), P(MONO(SSID), "cell")], [P(B("Password"), "cell"), P(MONO(PSK), "cell")]],
             colWidths=[1.2 * inch, 3.6 * inch])
cred.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, ACC), ("BACKGROUND", (0, 0), (0, -1), SOFT),
                          ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE), ("TOPPADDING", (0, 0), (-1, -1), 7),
                          ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
story += [Table([[cred]], colWidths=[7.0 * inch], style=[("LEFTPADDING", (0, 0), (-1, -1), 22)]), Spacer(1, 6)]
story += steps([
    'The phone may say "No internet". Choose to stay connected. Turn off mobile data and any VPN.',
    f'Open {MONO(ADDR)} in the browser. If it does not load, type {MONO("http://" + ADDR)}. Bookmark it.',
    f'To finish, press {BTN("End check-in now")}, or double tap the button again, or just wait 10 minutes.',
], start=4)
story += [Spacer(1, 4), box([P(B("If the password is refused")),
                             P('1. Check the light is blinking rapidly first. Joining too early or after the 10 minutes are up '
                               'can show as a wrong password.<br/>'
                               '2. Forget the network on your device (iPhone: Settings, Wi-Fi, (i) next to the network, '
                               'Forget This Network) and join again.<br/>'
                               '3. Type it by hand: all lowercase, with plain hyphens between the words.<br/>'
                               '4. Try a second time. The unit is busy recording and is sometimes slow to answer; '
                               'some phones report that as "Incorrect password".', "body")], WARN, WARNLINE)]

# ---------------- Status page tour ----------------
story += [P("The status page, top to bottom", "h1"),
          P("The page updates itself every few seconds. Every button that changes something asks you to confirm first.")]

story += [P("1. Status bar", "h2"),
          table([["Colour / text", "Meaning"],
                 ["Green: Capturing", "Recording normally."],
                 ["Yellow", "Recording but needs attention (shows why), or still starting."],
                 ["Red", "Capture stopped, adapter missing or error, or SD card full."],
                 ["Lost connection to the unit", "Your device left the check-in network, or the check-in ended."]],
                [2.0 * inch, 5.0 * inch]),
          Spacer(1, 10),
          table([["Button", "What it does"],
                 [BTN("Stop capture"), "Stops recording. It stays stopped until you press Start or power-cycle the unit. "
                                       "The light goes solid."],
                 [BTN("Start capture"), "Starts recording again in a new session. Shown only while stopped."]],
                [2.0 * inch, 5.0 * inch])]

story += [P("2. Transmitting box (yellow)", "h2"),
          P("Shown during a check-in, with a countdown to auto-off."),
          table([["Button", "What it does"],
                 [BTN("Extend 10 min"), "Resets the countdown to 10 minutes. Use it while downloading large files."],
                 [BTN("End check-in now"), "Switches the check-in network off. The page goes offline and the unit goes silent. "
                                           "Recording continues."]],
                [2.0 * inch, 5.0 * inch])]

story += [P("3. Numbers, charts and System", "h2"),
          table([["Tile", "What it shows"],
                 ["Listening on", "The band and channel the radio is on right now. It changes as it hops."],
                 ["Packets per second / received", "How busy the air is, and the total recorded this session."],
                 ["pcap files this session", "Size and number of files recorded since the session started."],
                 ["Networks / Devices", "Active (recently heard) out of total seen."],
                 ["SD free", "Space left, with an estimate of recording time left."],
                 ["Battery", "Charge level; says so when the charger is connected."],
                 ["Charts", "Packets per second (last 5 minutes), networks per channel, and encryption types seen."],
                 ["System", "Battery voltage, charging, temperature, load, memory, power warnings, time powered on, "
                            "channels being hopped, and total stored on the SD card."]],
                [2.0 * inch, 5.0 * inch])]

story += [P("4. Networks table", "h2"),
          P(f'Every Wi-Fi network heard: {B("Name")}, {B("Signal")}, {B("Ch")} (channel), {B("Security")}, '
            f'{B("Devices")}, {B("Data")}, {B("Address")} (BSSID) and {B("Last seen")}. Hidden networks show as (hidden).'),
          table([["Control", "How to use it"],
                 ["Filter box", "Type part of a name, address, channel number or security type (for example "
                                "<i>WPA3</i>, <i>149</i>, or <i>OPN</i> for open networks). Only matching rows stay. It matches "
                                "anywhere in the row, so a short number can also match part of an address."],
                 ["Column headers", "Tap a header to sort by it. Tap again to reverse."],
                 ["Row checkbox", "Ticks that network for Focus."],
                 ["Header checkbox", "Ticks every network currently shown, so it works together with the filter."]],
                [2.0 * inch, 5.0 * inch])]

story += [P("5. Devices table", "h2"),
          P(f'Phones, laptops and other clients heard: {B("Address")}, {B("Signal")}, {B("Packets")}, '
            f'{B("Connected to")} (which network) and {B("Searching for")} (network names the device is asking for). '
            f'It has its own filter box and sortable headers, just like the Networks table.')]

# ---------------- Focus ----------------
story += [PageBreak(), P("Focus: concentrate on chosen networks", "h1"),
          P("By default the radio hops all 98 channels and sees everything, but it spends only a moment on each. "
            "Focus makes it hop only the channels of the networks you choose, so it captures far more of their "
            "traffic. Focus still only listens.")]
story += [P("Option A: pick from the list", "h2")]
story += steps([
    "In the Networks table, tick one or more rows.",
    f'Press {BTN("Focus on selected")} and confirm.',
    f'Within about 20 seconds a new session named {MONO("focus-...")} starts, and the Focus box shows the targets.',
])
story += [P("Option B: add by name or address", "h2")]
story += steps([
    f'In the Focus box, choose {B("SSID name")} or {B("BSSID (MAC)")} from the drop-down.',
    f'Type the network name, or an address like {MONO("AA:BB:CC:DD:EE:FF")}.',
    f'Press {BTN("Add to focus")} (or Enter). It is added to the targets already in focus.',
])
story += [P("Option C: filter, then select all", "h2")]
story += steps([
    f'Type into the Networks filter box, for example part of a name such as {MONO("Guest")}, or a channel.',
    "Tick the checkbox in the table header to select every matching network.",
    f'Press {BTN("Focus on selected")}.',
])
story += [Spacer(1, 4), box([P(B("Good to know about Focus")),
    P(f'&bull; {BTN("Focus on selected")} replaces the current targets with the ticked networks. '
      f'{BTN("Add to focus")} keeps the current targets and adds one more.<br/>'
      f'&bull; A target not heard yet shows as {B("pending")}. Focus locks on automatically once it appears.<br/>'
      f'&bull; Networks that share a channel need only one channel, so you may see fewer channels than targets.<br/>'
      f'&bull; {BTN("Back to all channels")} (shown only while focused) returns to normal scanning in a new '
      f'{MONO("cap-...")} session.<br/>'
      f'&bull; Powering off and on always returns to all channels.')])]

# ---------------- Files ----------------
story += [P("Sessions and files: download and delete", "h1"),
          P(f'Recordings are grouped into sessions named by start time (UTC). The newest is open at the top; '
            f'the one being recorded is marked {B("(recording)")}. Tap a session name to open or close it.'),
          table([["Control", "What it does"],
                 ["File name (link)", "Downloads that one file."],
                 ["Download whole session (.tar)", "Downloads every file in the session as one archive."],
                 [BTN("Delete"), "Deletes that one file, after you confirm. Permanent."],
                 [BTN("Delete session"), "Deletes the session and all its files, after you confirm. Permanent. "
                                         "Greyed out for the session being recorded."]],
                [2.2 * inch, 4.8 * inch]),
          Spacer(1, 4),
          P("The file list refreshes every 30 seconds. If something you deleted still shows, wait a moment or reload "
            "the page. Right after a Focus or Start, the previous session can still show as recording for up to 30 "
            "seconds; reload the page to delete it.", "small")]

story += [KeepTogether([P("Files you will see", "h2"),
          table([["File", "Contents"],
                 [MONO("cap-YYYYMMDD-HHMMSS.pcap"), "Full packets with radio details (channel, signal). "
                                                    "A new file every 5 minutes. Open in Wireshark."],
                 [MONO("focus-YYYYMMDD-HHMMSS.pcap"), "The same, recorded while in Focus."],
                 [MONO("summary-01.csv"), "Summary of every network and device seen (opens in Excel)."]],
                [2.6 * inch, 4.4 * inch])])]

story += [KeepTogether([P("Large downloads: SFTP", "h2"),
          P("For big sessions, SFTP is faster than the browser. Use FileZilla, Cyberduck or WinSCP while connected "
            "to the check-in network (press Extend 10 min first)."),
          table([["Setting", "Value"], ["Host / port", MONO(ADDR) + "&nbsp;&nbsp;port " + MONO("22")], ["Username", MONO(USER)],
                 ["Password", MONO(PW)], ["Folder", MONO("/var/lib/capture/") + " (one folder per session)"]],
                [1.6 * inch, 5.4 * inch])])]

# ---------------- Troubleshooting ----------------
story += [KeepTogether([P("Troubleshooting", "h1"),
          table([["Problem", "Try this"],
                 ["Light stays solid", "Wait 4 minutes after power-on. Check the Wi-Fi adapter is firmly plugged in. "
                                       "Power off and on."],
                 ["No check-in network appears", "Double tap once only, then wait 30 seconds. Extra taps switch it off "
                                                 "again. The light should blink rapidly."],
                 ["Password refused", "See the box on the check-in page: wait for rapid blink, forget the network, "
                                      "type by hand, try twice."],
                 ["Page will not load", f'Type {MONO("http://" + ADDR)}. Turn off mobile data and VPN. Stay connected when '
                                        'the phone says no internet.'],
                 ["Page says lost connection", "The check-in ended (10 minutes) or your phone switched networks. "
                                               "Double tap to start a new check-in."],
                 ["Light shows SOS", "Charge the battery, or download and delete old sessions to free space."]],
                [2.0 * inch, 5.0 * inch])])]

story += [KeepTogether([P("Good to know", "h1"),
    P(f'&bull; {B("Channels:")} 2.4 GHz channels 1-11, all of 5 GHz, and 6 GHz (98 channels, US rules).<br/>'
      f'&bull; {B("One radio:")} it hops between channels, so short bursts on another channel can be missed. Use Focus.<br/>'
      f'&bull; {B("Timestamps")} come from the battery board clock, in UTC. No network needed.<br/>'
      f'&bull; {B("Charging:")} use the PiSugar USB-C port. It keeps recording while charging.<br/>'
      f'&bull; {B("Power off")} cuts power immediately. Files are saved continuously, so at most the last few '
      f'seconds are lost.<br/>'
      f'&bull; {B("Keep the Wi-Fi adapter plugged in.")} Without it nothing is recorded and the light goes solid.')])]


def footer(c, doc):
    c.saveState()
    c.setFont("Helvetica", 7.5); c.setFillColor(DIM)
    c.drawString(0.75 * inch, 0.5 * inch, f"Wi-Fi Capture Unit - {SSID}")
    c.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
    c.restoreState()


doc = BaseDocTemplate(out, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                      topMargin=0.7 * inch, bottomMargin=0.8 * inch,
                      title="Wi-Fi Capture Unit - User Guide", author="")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=footer)])
doc.build(story)
print("wrote", out)
