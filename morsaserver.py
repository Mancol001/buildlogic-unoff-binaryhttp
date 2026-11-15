from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import sys
import time
import threading

# Make colours + symbols work in Windows terminals too
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
os.system("")  # enables ANSI escape codes on Windows 10+

# ---------------------------------------------------------------------------
# Terminal styling
# ---------------------------------------------------------------------------
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
GREY = "\033[90m"

CHANNEL_COLORS = [CYAN, MAGENTA, YELLOW, GREEN]


def ts():
    return f"{GREY}{time.strftime('%H:%M:%S')}{RESET}"


def log(tag, color, message):
    print(f"{ts()} {color}{BOLD}{tag:<7}{RESET} {message}", flush=True)


def render_channels(value):
    """Turns '10000100' into a coloured per-channel LED display."""
    parts = []
    for i in range(4):
        pair = value[i * 2:i * 2 + 2]
        color = CHANNEL_COLORS[i]
        leds = "".join(
            f"{color}●{RESET}" if bit == "1" else f"{GREY}○{RESET}"
            for bit in pair
        )
        parts.append(f"{DIM}CH{i + 1}{RESET} {leds}")
    return "   ".join(parts)


def describe(value):
    """Human readable summary of what is active."""
    active = []
    for i in range(4):
        pair = value[i * 2:i * 2 + 2]
        if pair == "10":
            active.append(f"CH{i + 1} SHORT")
        elif pair == "01":
            active.append(f"CH{i + 1} LONG")
        elif pair == "11":
            active.append(f"CH{i + 1} BOTH")
    return ", ".join(active) if active else "idle"


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
current_value = "00000000"

latest_sequences = {}
data_lock = threading.Lock()

# stats for the CLI (these never touch /read behaviour)
stats_lock = threading.Lock()
stats = {
    "writes": 0,
    "ignored": 0,
    "errors": 0,
    "reads_window": 0,
    "reads_total": 0,
    "readers": set(),
    "readers_window": set(),
    "started": time.time(),
}


HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>4-Channel Transmitter</title>

<style>
:root {
    --bg: #07070c;
    --panel: rgba(255, 255, 255, 0.04);
    --border: rgba(255, 255, 255, 0.09);
    --text: #e9e9f3;
    --muted: #7d7d96;
    --c1: #00e5ff;
    --c2: #ff2bd6;
    --c3: #ffd400;
    --c4: #3dff8b;
    --accent: #8a5cff;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    min-height: 100vh;
    background:
        radial-gradient(900px 500px at 15% -10%, rgba(138, 92, 255, 0.22), transparent 60%),
        radial-gradient(800px 500px at 100% 110%, rgba(0, 229, 255, 0.14), transparent 60%),
        var(--bg);
    color: var(--text);
    font-family: "Segoe UI", system-ui, Arial, sans-serif;
    text-align: center;
    padding: 36px 16px 60px;
    -webkit-user-select: none;
    user-select: none;
    overflow-x: hidden;
}

/* faint scanlines */
body::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    background: repeating-linear-gradient(
        0deg, rgba(255,255,255,0.018) 0 1px, transparent 1px 3px);
    z-index: 0;
}

.wrap { position: relative; z-index: 1; max-width: 760px; margin: 0 auto; }

h1 {
    margin: 0;
    font-size: 34px;
    letter-spacing: 6px;
    text-transform: uppercase;
    font-weight: 800;
    background: linear-gradient(90deg, var(--c1), var(--accent), var(--c2));
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    filter: drop-shadow(0 0 14px rgba(138, 92, 255, 0.45));
}

.subtitle {
    margin: 8px 0 0;
    color: var(--muted);
    font-size: 13px;
    letter-spacing: 3px;
    text-transform: uppercase;
}

.conn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-top: 16px;
    padding: 6px 14px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--panel);
    font-size: 12px;
    color: var(--muted);
    font-family: Consolas, monospace;
}

.dot {
    width: 9px; height: 9px;
    border-radius: 50%;
    background: #555;
    box-shadow: 0 0 0 0 transparent;
}
.dot.ok { background: var(--c4); box-shadow: 0 0 10px var(--c4); }
.dot.bad { background: #ff4757; box-shadow: 0 0 10px #ff4757; }

/* ---------- channels ---------- */
.channels {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin: 34px 0 18px;
}

.channel {
    --col: var(--c1);
    position: relative;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 16px 8px 14px;
    cursor: pointer;
    transition: transform .15s, border-color .2s, box-shadow .2s, background .2s;
    backdrop-filter: blur(6px);
}
.channel:nth-child(1) { --col: var(--c1); }
.channel:nth-child(2) { --col: var(--c2); }
.channel:nth-child(3) { --col: var(--c3); }
.channel:nth-child(4) { --col: var(--c4); }

.channel:hover { transform: translateY(-3px); }

.channel.selected {
    border-color: var(--col);
    background: color-mix(in srgb, var(--col) 10%, transparent);
    box-shadow: 0 0 24px color-mix(in srgb, var(--col) 35%, transparent),
                inset 0 0 20px color-mix(in srgb, var(--col) 10%, transparent);
}

.channel.active {
    animation: pulse .5s ease-in-out infinite alternate;
}
@keyframes pulse {
    from { box-shadow: 0 0 18px color-mix(in srgb, var(--col) 40%, transparent); }
    to   { box-shadow: 0 0 44px color-mix(in srgb, var(--col) 85%, transparent); }
}

.channel .key {
    position: absolute;
    top: 8px; left: 10px;
    font-size: 10px;
    color: var(--muted);
    font-family: Consolas, monospace;
}

.channel h3 {
    margin: 4px 0 10px;
    font-size: 11px;
    letter-spacing: 2px;
    color: var(--muted);
}
.channel.selected h3 { color: var(--col); }

.leds {
    display: flex;
    justify-content: center;
    gap: 10px;
    margin-bottom: 10px;
}
.led {
    width: 16px; height: 16px;
    border-radius: 50%;
    background: #1a1a24;
    border: 1px solid rgba(255,255,255,0.1);
    transition: background .05s, box-shadow .05s;
}
.led.on {
    background: var(--col);
    box-shadow: 0 0 14px var(--col), 0 0 28px var(--col);
}
.led-label {
    font-size: 9px;
    color: var(--muted);
    letter-spacing: 1px;
}

.channel-value {
    font-family: Consolas, monospace;
    font-size: 22px;
    margin-top: 6px;
}

/* ---------- scope ---------- */
.scope-box {
    border: 1px solid var(--border);
    border-radius: 16px;
    background: rgba(0, 0, 0, 0.35);
    padding: 10px;
    margin-bottom: 18px;
}
canvas#scope { width: 100%; height: 150px; display: block; }

#output {
    font-family: Consolas, monospace;
    font-size: 26px;
    letter-spacing: 2px;
    margin: 6px 0 22px;
    text-shadow: 0 0 12px rgba(138, 92, 255, 0.6);
}

/* ---------- buttons ---------- */
.buttons {
    display: flex;
    justify-content: center;
    gap: 22px;
    flex-wrap: wrap;
}

.transmit {
    position: relative;
    width: 170px;
    height: 100px;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 2px;
    border: 1px solid var(--border);
    border-radius: 18px;
    background: linear-gradient(160deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
    color: white;
    cursor: pointer;
    user-select: none;
    touch-action: none;
    transition: transform .08s, box-shadow .2s, background .2s;
    overflow: hidden;
}
.transmit small {
    display: block;
    margin-top: 6px;
    font-size: 11px;
    font-weight: 400;
    letter-spacing: 1px;
    color: var(--muted);
    font-family: Consolas, monospace;
}
.transmit:hover { box-shadow: 0 0 22px rgba(138, 92, 255, 0.35); }
.transmit.down, .transmit:active {
    transform: scale(0.96);
    background: linear-gradient(160deg, #9a6bff, #5a2fe0);
    box-shadow: 0 0 40px rgba(138, 92, 255, 0.8);
}
.transmit.down small, .transmit:active small { color: #e3d6ff; }

.transmit::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at center, rgba(255,255,255,0.35), transparent 60%);
    opacity: 0;
    transform: scale(0.2);
}
.transmit.down::after { animation: ripple .6s ease-out infinite; }
@keyframes ripple {
    from { opacity: .8; transform: scale(0.2); }
    to   { opacity: 0;  transform: scale(1.6); }
}

#status {
    margin-top: 26px;
    color: var(--muted);
    font-size: 14px;
    letter-spacing: 1px;
}

/* ---------- log ---------- */
.log {
    margin-top: 26px;
    text-align: left;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: rgba(0, 0, 0, 0.35);
    padding: 12px 14px;
    font-family: Consolas, monospace;
    font-size: 12px;
    height: 130px;
    overflow: hidden;
    display: flex;
    flex-direction: column-reverse;
}
.log div { color: var(--muted); white-space: nowrap; }
.log div:first-child { color: var(--text); }
.log .err { color: #ff6b7a; }

/* ---------- settings ---------- */
.audio-settings {
    margin-top: 28px;
    display: flex;
    justify-content: center;
    gap: 30px;
    flex-wrap: wrap;
    color: var(--muted);
    font-size: 13px;
}
.audio-settings label { display: flex; align-items: center; gap: 10px; }
.audio-settings input[type=range] {
    width: 150px;
    accent-color: var(--accent);
}
.audio-settings span {
    font-family: Consolas, monospace;
    color: var(--text);
    min-width: 54px;
    text-align: left;
}

.hint {
    margin-top: 22px;
    font-size: 11px;
    color: #55556b;
    letter-spacing: 1px;
}
kbd {
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 1px 6px;
    background: var(--panel);
    font-family: Consolas, monospace;
}

@media (max-width: 520px) {
    .channels { grid-template-columns: repeat(2, 1fr); }
    h1 { font-size: 24px; letter-spacing: 3px; }
}
</style>
</head>

<body>
<div class="wrap">

<h1>4-Channel Transmitter</h1>
<p class="subtitle">hold a button to transmit</p>

<div class="conn"><span class="dot" id="dot"></span><span id="conn">idle</span></div>

<div class="channels" id="channels"></div>

<div class="scope-box"><canvas id="scope"></canvas></div>

<div id="output">[00] [00] [00] [00]</div>

<div class="buttons">

    <button class="transmit" id="btn1">
        SHORT
        <small>200ms &middot; <kbd>Z</kbd></small>
    </button>

    <button class="transmit" id="btn2">
        LONG
        <small>500ms &middot; <kbd>X</kbd></small>
    </button>

</div>

<div id="status">Ready</div>

<div class="log" id="log"></div>

<div class="audio-settings">

    <label>
        Volume
        <input type="range" id="volume" min="0" max="100" value="30">
        <span id="volumeValue">30%</span>
    </label>

    <label>
        Frequency
        <input type="range" id="frequency" min="200" max="2000" value="800">
        <span id="frequencyValue">800Hz</span>
    </label>

</div>

<div class="hint">
    <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> <kbd>4</kbd> select channel &nbsp;&middot;&nbsp;
    hold <kbd>Z</kbd> / <kbd>X</kbd> to transmit
</div>

</div>

<script>

const channelContainer = document.getElementById("channels");
const output = document.getElementById("output");
const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const dot = document.getElementById("dot");
const connEl = document.getElementById("conn");

const session = crypto.randomUUID();

let sequence = 0;

let selectedChannel = 0;

let channels = [
    "00",
    "00",
    "00",
    "00"
];


// ---------- activity log ----------

function addLog(message, isError) {

    const line = document.createElement("div");

    const t = new Date().toLocaleTimeString([], { hour12: false });

    line.textContent = t + "  " + message;

    if (isError) line.className = "err";

    logEl.prepend(line);

    while (logEl.children.length > 12) {
        logEl.removeChild(logEl.lastChild);
    }

}


function setConnection(ok, text) {

    dot.className = "dot " + (ok ? "ok" : "bad");
    connEl.textContent = text;

}


// ---------- audio system ----------

let audioContext = null;
let oscillator = null;
let gainNode = null;

let audioEnabled = false;

const volumeSlider = document.getElementById("volume");
const frequencySlider = document.getElementById("frequency");

volumeSlider.oninput = () => {

    document.getElementById("volumeValue").textContent =
        volumeSlider.value + "%";

};

frequencySlider.oninput = () => {

    document.getElementById("frequencyValue").textContent =
        frequencySlider.value + "Hz";

};


// Initialize audio after user interaction

async function initializeAudio() {

    if (!audioContext) {

        audioContext = new (
            window.AudioContext ||
            window.webkitAudioContext
        )();

    }

    if (audioContext.state === "suspended") {
        await audioContext.resume();
    }

    audioEnabled = true;

}


// Play one beep that lasts exactly durationMs (200 for SHORT, 500 for LONG).
// While a button is held the beep repeats with equal silence in between
// (beep, pause, beep...) so SHORT and LONG are clearly different.
// firstPress = true skips the repeat gate so a new press always beeps.

let lastBeepStart = -Infinity;

async function playBeep(durationMs, firstPress) {

    await initializeAudio();

    const nowTime = audioContext.currentTime;

    const period = (durationMs * 2) / 1000;

    if (!firstPress && nowTime < lastBeepStart + period - 0.03) return;

    lastBeepStart = nowTime;

    stopBeep();

    oscillator = audioContext.createOscillator();

    gainNode = audioContext.createGain();

    oscillator.type = "sine";

    oscillator.frequency.value =
        Number(frequencySlider.value);

    const volume = Number(volumeSlider.value) / 100;
    const length = durationMs / 1000;
    const fade = 0.005;   // tiny fade in/out so there are no clicks

    gainNode.gain.setValueAtTime(0, nowTime);
    gainNode.gain.linearRampToValueAtTime(volume, nowTime + fade);
    gainNode.gain.setValueAtTime(volume, nowTime + length - fade);
    gainNode.gain.linearRampToValueAtTime(0, nowTime + length);

    oscillator.connect(gainNode);

    gainNode.connect(audioContext.destination);

    const osc = oscillator;
    const gain = gainNode;

    osc.onended = () => {

        try { osc.disconnect(); gain.disconnect(); } catch (e) {}

        if (oscillator === osc) {
            oscillator = null;
            gainNode = null;
        }

    };

    osc.start(nowTime);
    osc.stop(nowTime + length);

}


// Stop beep

function stopBeep() {

    if (!oscillator) return;

    oscillator.stop();

    oscillator.disconnect();
    gainNode.disconnect();

    oscillator = null;
    gainNode = null;

}


// Update beep settings while playing

function updateAudioSettings() {

    if (!oscillator || !gainNode) return;

    // frequency changes apply live; volume applies from the next beep
    oscillator.frequency.value =
        Number(frequencySlider.value);

}

volumeSlider.addEventListener("input", updateAudioSettings);
frequencySlider.addEventListener("input", updateAudioSettings);


// ---------- channels ----------

function selectChannel(i) {

    selectedChannel = i;

    document.querySelectorAll(".channel").forEach(
        (element, index) => {
            element.classList.toggle(
                "selected",
                index === selectedChannel
            );
        }
    );

    statusEl.textContent =
        "Selected Channel " + (i + 1);

}

for (let i = 0; i < 4; i++) {

    const channel = document.createElement("div");

    channel.className = "channel";

    channel.innerHTML = `
        <span class="key">${i + 1}</span>
        <h3>CHANNEL ${i + 1}</h3>
        <div class="leds">
            <div class="led"></div>
            <div class="led"></div>
        </div>
        <div class="led-label">SHORT &nbsp; LONG</div>
        <div class="channel-value">00</div>
    `;

    channel.onclick = () => selectChannel(i);

    channelContainer.appendChild(channel);

}


// Update channel display

function updateChannels() {

    document.querySelectorAll(".channel").forEach(
        (element, index) => {

            element.querySelector(".channel-value").textContent =
                channels[index];

            const leds = element.querySelectorAll(".led");

            leds[0].classList.toggle("on", channels[index][0] === "1");
            leds[1].classList.toggle("on", channels[index][1] === "1");

            element.classList.toggle("active", channels[index] !== "00");

        }
    );

    output.textContent = channels
        .map(value => `[${value}]`)
        .join(" ");

}


// Generate original 8-bit value

function getValue() {

    return channels.join("");

}


// ---------- scope (scrolling signal trace) ----------

const canvas = document.getElementById("scope");
const ctx = canvas.getContext("2d");

const LANE_COLORS = ["#00e5ff", "#ff2bd6", "#ffd400", "#3dff8b"];
const HISTORY = 400;

const history = [[], [], [], []];

function resizeCanvas() {

    const ratio = window.devicePixelRatio || 1;

    canvas.width = canvas.clientWidth * ratio;
    canvas.height = canvas.clientHeight * ratio;

    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function drawScope() {

    const w = canvas.clientWidth;
    const h = canvas.clientHeight;

    ctx.clearRect(0, 0, w, h);

    const laneHeight = h / 4;

    for (let lane = 0; lane < 4; lane++) {

        history[lane].push(channels[lane] !== "00" ? 1 : 0);

        if (history[lane].length > HISTORY) history[lane].shift();

        const top = lane * laneHeight + 6;
        const bottom = (lane + 1) * laneHeight - 6;

        // baseline
        ctx.strokeStyle = "rgba(255,255,255,0.07)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, bottom);
        ctx.lineTo(w, bottom);
        ctx.stroke();

        // trace
        ctx.strokeStyle = LANE_COLORS[lane];
        ctx.shadowColor = LANE_COLORS[lane];
        ctx.shadowBlur = 8;
        ctx.lineWidth = 2;
        ctx.beginPath();

        const step = w / HISTORY;
        const offset = w - history[lane].length * step;

        history[lane].forEach((sample, index) => {

            const x = offset + index * step;
            const y = sample ? top : bottom;

            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                const prev = history[lane][index - 1];
                const prevY = prev ? top : bottom;
                ctx.lineTo(x, prevY);
                ctx.lineTo(x, y);
            }

        });

        ctx.stroke();
        ctx.shadowBlur = 0;

        // label
        ctx.fillStyle = LANE_COLORS[lane];
        ctx.font = "10px Consolas, monospace";
        ctx.fillText("CH" + (lane + 1), 6, top + 9);

    }

    requestAnimationFrame(drawScope);

}

drawScope();


// ---------- send transmission ----------

async function sendValue(value) {

    const currentSequence = ++sequence;

    output.textContent = value.match(/.{2}/g)
        .map(group => `[${group}]`)
        .join(" ");

    const started = performance.now();

    try {

        const response = await fetch("/write", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            cache: "no-store",

            body: JSON.stringify({

                value: value,
                sequence: currentSequence,
                session: session

            })

        });

        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }

        const ms = Math.round(performance.now() - started);

        setConnection(true, "online \u00b7 " + ms + "ms");

        addLog("#" + currentSequence + "  " + value + "  (" + ms + "ms)");

    } catch (error) {

        setConnection(false, "offline");

        statusEl.textContent =
            "Connection error: " + error.message;

        addLog("#" + currentSequence + "  " + error.message, true);

    }

}


// Activate a specific bit in selected channel

function transmit(bit) {

    channels = [
        "00",
        "00",
        "00",
        "00"
    ];

    const bits = channels[selectedChannel].split("");

    bits[bit] = "1";

    channels[selectedChannel] = bits.join("");

    updateChannels();

    sendValue(getValue());

}


// Reset all channels

function resetChannels() {

    channels = [
        "00",
        "00",
        "00",
        "00"
    ];

    updateChannels();

    sendValue("00000000");

}


// ---------- button transmission system ----------

const controls = {};

function setupButton(id, interval, bit) {

    const button = document.getElementById(id);

    let holding = false;
    let timeout = null;

    async function scheduleNext() {

        if (!holding) return;

        const now = performance.now();

        const nextTick =
            (Math.floor(now / interval) + 1) * interval;

        timeout = setTimeout(() => {

            if (!holding) return;

            transmit(bit);

            playBeep(interval, false).catch(() => {});

            scheduleNext();

        }, nextTick - now);

    }


    async function start() {

        if (holding) return;

        holding = true;

        button.classList.add("down");

        statusEl.textContent =
            "Transmitting on Channel " + (selectedChannel + 1);

        transmit(bit);

        try {

            await playBeep(interval, true);

        } catch (error) {

            statusEl.textContent = "Audio error: " + error.message;

        }

        if (holding) {
            scheduleNext();
        }

    }


    function stop() {

        if (!holding) return;

        holding = false;

        button.classList.remove("down");

        clearTimeout(timeout);

        // the current beep is left to finish so a quick tap still plays
        // its full 200ms / 500ms

        resetChannels();

        statusEl.textContent =
            "Channel " + (selectedChannel + 1) + " selected";

    }


    button.addEventListener("pointerdown", event => {

        event.preventDefault();

        if (holding) return;

        button.setPointerCapture(event.pointerId);

        start();

    });

    button.addEventListener("pointerup", stop);
    button.addEventListener("pointercancel", stop);
    button.addEventListener("lostpointercapture", stop);

    controls[id] = { start, stop };

}


// Initialize buttons

setupButton("btn1", 200, 0);
setupButton("btn2", 500, 1);


// ---------- keyboard shortcuts ----------

window.addEventListener("keydown", event => {

    if (event.repeat) return;

    if (["1", "2", "3", "4"].includes(event.key)) {
        selectChannel(Number(event.key) - 1);
    } else if (event.key.toLowerCase() === "z") {
        controls.btn1.start();
    } else if (event.key.toLowerCase() === "x") {
        controls.btn2.start();
    }

});

window.addEventListener("keyup", event => {

    if (event.key.toLowerCase() === "z") controls.btn1.stop();
    if (event.key.toLowerCase() === "x") controls.btn2.stop();

});


// Initial display

selectChannel(0);
statusEl.textContent = "Ready";

updateChannels();

addLog("session " + session.slice(0, 8) + " ready");

</script>

</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):

    # Silence the default noisy one-line-per-request logging;
    # the pretty CLI output below replaces it.
    def log_message(self, format, *args):
        pass

    # Reads are tracked here (not inside the /read handler, which is untouched).
    def log_request(self, code="-", size="-"):

        if self.command == "GET" and self.path == "/read":

            ip = self.client_address[0]

            with stats_lock:

                stats["reads_window"] += 1
                stats["reads_total"] += 1
                stats["readers_window"].add(ip)

                is_new = ip not in stats["readers"]
                stats["readers"].add(ip)

            if is_new:
                log("READER", BLUE, f"new reader connected: {BOLD}{ip}{RESET}")

        elif self.command == "GET" and self.path == "/":

            log("PAGE", BLUE, f"page opened by {BOLD}{self.client_address[0]}{RESET}")

    def do_GET(self):

        if self.path == "/":

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            self.wfile.write(HTML.encode())

        elif self.path == "/read":

            with data_lock:
                value = current_value

            self.send_json({
                "value": value
            })

        else:

            self.send_error(404)


    def do_POST(self):

        global current_value

        if self.path != "/write":

            self.send_error(404)
            return

        try:

            length = int(self.headers.get("Content-Length", 0))

            data = json.loads(self.rfile.read(length))

            value = data.get("value")
            seq = data.get("sequence")
            session_id = data.get("session")

            if (
                not isinstance(value, str)
                or len(value) != 8
                or any(bit not in "01" for bit in value)
            ):

                with stats_lock:
                    stats["errors"] += 1

                log("REJECT", RED, f"invalid value {value!r}")
                self.send_error(400, "Invalid value")
                return

            if (
                not isinstance(seq, int)
                or isinstance(seq, bool)
                or seq < 1
                or not isinstance(session_id, str)
            ):

                with stats_lock:
                    stats["errors"] += 1

                log("REJECT", RED, "invalid sequence / session")
                self.send_error(400, "Invalid sequence")
                return

            with data_lock:

                last_seq = latest_sequences.get(session_id, 0)

                if seq <= last_seq:

                    with stats_lock:
                        stats["ignored"] += 1

                    log(
                        "STALE",
                        YELLOW,
                        f"{DIM}seq {seq} <= {last_seq} from "
                        f"{session_id[:8]} ignored{RESET}"
                    )

                    self.send_json({
                        "status": "ignored",
                        "reason": "Outdated transmission"
                    })

                    return

                latest_sequences[session_id] = seq
                previous_value = current_value
                current_value = value

            with stats_lock:
                stats["writes"] += 1

            released = value == "00000000"

            tag = "RELEASE" if released else "TX"
            color = GREY if released else GREEN

            log(
                tag,
                color,
                f"{render_channels(value)}   "
                f"{DIM}{value}  seq {seq}  "
                f"{session_id[:8]}  {describe(value)}{RESET}"
            )

            self.send_json({
                "status": "ok",
                "value": current_value,
                "sequence": seq
            })

        except Exception as error:

            with stats_lock:
                stats["errors"] += 1

            log("ERROR", RED, str(error))
            self.send_error(400, "Invalid request")


    def send_json(self, data):

        response = json.dumps(data).encode()

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate"
        )

        self.send_header(
            "Content-Length",
            str(len(response))
        )

        self.end_headers()

        self.wfile.write(response)


def read_summary_loop():
    """Every 10s, prints a quiet one-liner about /read polling (if any)."""

    while True:

        time.sleep(10)

        with stats_lock:

            reads = stats["reads_window"]
            readers = len(stats["readers_window"])

            stats["reads_window"] = 0
            stats["readers_window"] = set()

        if reads:
            log(
                "READS",
                BLUE,
                f"{DIM}{reads} polls in the last 10s from "
                f"{readers} reader{'s' if readers != 1 else ''}{RESET}"
            )


def uptime():
    seconds = int(time.time() - stats["started"])
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


# ---------------------------------------------------------------------------
# Render-compatible server startup
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", 3077))

server = ThreadingHTTPServer(
    ("0.0.0.0", PORT),
    Handler
)

ip = local_ip()

print()
print(f"{MAGENTA}{BOLD}  ╔══════════════════════════════════════╗{RESET}")
print(f"{MAGENTA}{BOLD}  ║{RESET}{BOLD}      4-CHANNEL  TRANSMITTER  SERVER  {MAGENTA}{BOLD}║{RESET}")
print(f"{MAGENTA}{BOLD}  ╚══════════════════════════════════════╝{RESET}")
print()

print(f"  {BOLD}Port    {RESET} {CYAN}{PORT}{RESET}")
print(f"  {BOLD}Network {RESET} {CYAN}0.0.0.0:{PORT}{RESET}")

if not os.environ.get("RENDER"):
    print(f"  {BOLD}Local   {RESET} {CYAN}http://localhost:{PORT}{RESET}")
    print(f"  {BOLD}Network {RESET} {CYAN}http://{ip}:{PORT}{RESET}")

print()
print(f"  {GREEN}POST{RESET} /write   {DIM}send an 8-bit value{RESET}")
print(f"  {BLUE}GET {RESET} /read    {DIM}read the current value{RESET}")
print()
print(f"  {DIM}4 channels · 2 bits each · SHORT = bit 1 · LONG = bit 2{RESET}")
print(f"  {DIM}sequencing: on · cache prevention: on · Ctrl+C to quit{RESET}")
print()
print(f"  {GREY}{'─' * 60}{RESET}")
print(f"  {DIM}live log:{RESET}")
print()

threading.Thread(target=read_summary_loop, daemon=True).start()

try:
    server.serve_forever()

except KeyboardInterrupt:
    print()
    print(f"  {GREY}{'─' * 60}{RESET}")
    print(f"  {BOLD}Session summary{RESET}  {DIM}(uptime {uptime()}){RESET}")
    print(f"    transmissions : {GREEN}{stats['writes']}{RESET}")
    print(f"    ignored (old) : {YELLOW}{stats['ignored']}{RESET}")
    print(f"    errors        : {RED}{stats['errors']}{RESET}")
    print(f"    /read polls   : {BLUE}{stats['reads_total']}{RESET} "
          f"from {len(stats['readers'])} reader(s)")
    print()
    print("  Shutting down...")

finally:
    server.server_close()