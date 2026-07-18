# Syncora

> **Wireless screens, made simple.**

Syncora is an open-source experiment for displaying a computer screen on another device over a local network. The current version mirrors the primary screen and system output audio over low-latency WebRTC, with MJPEG video as a compatibility fallback. It does **not** create an extended virtual display.

## Requirements

- Python 3.10 or newer
- Debian Linux (the initial development platform)
- A graphical X11 or Wayland session
- A PC and viewing device on the same trusted local network

On Debian/Ubuntu, install the virtual-environment module and the Wayland capture components:

```bash
sudo apt install python3-venv python3-gi gir1.2-gstreamer-1.0 gstreamer1.0-pipewire gstreamer1.0-plugins-base
```

## Install

From the project directory:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The Internet is only needed to download dependencies during installation. Syncora itself uses no cloud service, account, telemetry, external STUN/TURN server, or Internet connection.

## Run

```bash
source .venv/bin/activate
python -m syncora.server
```

Syncora listens on every network interface at port `8080` and prints the address to open. From the TV or another device on the same Wi-Fi network, open that address in a browser, for example `http://192.168.1.42:8080`.

With the Fish shell, activate the environment with:

```fish
source .venv/bin/activate.fish
```

On Wayland, the desktop displays a system screen-selection dialog when the first viewer opens the stream. Select the monitor to share and approve the request. Syncora never bypasses this security dialog. On the receiving device, press **Enable sound** once; browsers require this interaction before playing audio.

If automatic address detection does not find the correct interface, find the PC address with:

```bash
hostname -I
```

Use the private LAN address (commonly beginning with `192.168.` or `10.`), followed by `:8080`. Your firewall must allow incoming TCP connections on the selected port.

## Configuration

Command-line flags are the simplest way to adjust capture:

```bash
python -m syncora.server --port 8080 --fps 15 --quality 75 --scale 1.0
```

- `--fps`: 1–30 frames per second
- `--quality`: JPEG quality from 1–95
- `--scale`: resize factor from 0.1–1.0 (try `0.5` on a slow network)
- `--port`: TCP port from 1–65535
- `--host`: listening address; the default `0.0.0.0` is required for LAN access

Equivalent environment variables are `SYNCORA_HOST`, `SYNCORA_PORT`, `SYNCORA_FPS`, `SYNCORA_JPEG_QUALITY`, and `SYNCORA_SCALE`. Command-line values take precedence.

The system audio monitor is detected from the default output with `pactl`. It can be overridden when needed:

```bash
SYNCORA_AUDIO_DEVICE=my_output.monitor python -m syncora.server
```

`--quality` applies only to the MJPEG compatibility stream. WebRTC selects its video bitrate dynamically according to browser and network conditions.

## Tests

Tests do not capture the screen and need no TV:

```bash
python -m unittest discover -v
python -m compileall -q syncora tests
```

With a server already running, an optional end-to-end WebRTC check is available:

```bash
python scripts/check_webrtc.py
```

## Security

There is currently **no authentication or encryption**. Anyone who can reach the selected port on the local network can view the screen, which may expose passwords, messages, or personal data. Only run Syncora on a trusted network, close it when finished, and do not expose port 8080 through a router or to the Internet.

## Current limitations

- Mirrors only the primary physical monitor; it is not an extended display.
- No input forwarding, access control, or TLS encryption. Audio captures the default system output; switching output devices while streaming may require restarting Syncora.
- WebRTC encoding currently uses the software codecs available through `aiortc`; high-resolution capture can therefore consume noticeable CPU. Older TV browsers fall back to the slower MJPEG stream.
- Wayland requires a working `xdg-desktop-portal` ScreenCast backend and PipeWire. Most current KDE and GNOME distributions provide one, but minimal distributions may require an additional desktop-specific portal package.
- The Flask development server is appropriate for a local prototype, not for Internet exposure.
- Browser full-screen support varies on smart TVs and may require remote-control interaction.

## Roadmap

- Connection PIN
- Authentication and encryption
- More efficient video encoding and lower latency
- More audio controls and automatic output-device switching
- Android TV and other platform applications
- Windows and macOS support
- A true extended virtual display

## License

Syncora is released under the [MIT License](LICENSE).
