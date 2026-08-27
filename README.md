# Office Pi Dashboard

A kiosk-mode dashboard for a Raspberry Pi Zero 2 WH driving a 10.1"
1280x800 touchscreen: today's Todoist tasks, your calendar, Hue lighting
controls for the room, and Bambu P1S print status - all in one always-on
4-quadrant screen, no internet dependency once it's running (the browser
only ever talks to `localhost`).

This is a prototype built to be cloned per-room: nothing is hardcoded to
one room or one printer - see [Config](#config) below.

```
+-------------------+-------------------+
|      Tasks        |      Calendar     |
|     (Todoist)      |  (Fastmail/iCloud) |
+-------------------+-------------------+
|      Lights        |      Printer      |
|       (Hue)         |    (Bambu P1S)     |
+-------------------+-------------------+
```

## Architecture

- **Backend**: Python/FastAPI (`/backend`), one poller module per
  integration (`pollers/todoist.py`, `calendar.py`, `hue.py`, `bambu.py`),
  each running as its own background asyncio task on its own interval.
  A poll failure never blanks a panel - the last good data stays on
  screen with a "stale" indicator until the next successful poll.
- **Frontend**: a single static page (`/frontend`) - vanilla HTML/CSS/JS,
  no build step, no framework. It polls `GET /api/state` every 5s and
  only touches the DOM for panels whose data actually changed.
- **Display**: Chromium in `--kiosk` mode pointed at `http://localhost:5000`
  - never the public internet, so the dashboard keeps working through
  wifi drops as long as the Pi itself is up.

## Repo layout

```
backend/          FastAPI app + pollers (each independently testable)
frontend/         index.html + style.css + app.js
setup/            kiosk boot config (.xinitrc, systemd units) + setup.sh
.env.example      secrets + machine-specific network info (copy -> .env)
config.yaml.example   room-specific, non-secret settings (copy -> config.yaml)
```

## Config

Two files, two purposes:

- **`.env`** (gitignored, never commit it) - secrets and things tied to
  your specific network: Todoist token, CalDAV credentials, Hue bridge IP
  + API key, Bambu printer IP + access code + serial.
- **`config.yaml`** (gitignored by default too, but this is the file worth
  keeping around per install) - room-specific but non-secret: which Hue
  group to control, the room's display name, poll intervals, Todoist
  filter tweaks. **This is the file a future "clone this for another
  room" setup actually edits.**

```
cp .env.example .env               # then fill in every value
cp config.yaml.example config.yaml # then adjust for this room
```

## Manual one-time setup steps

These can't be scripted away - each needs a human in the loop once:

### 1. Todoist
Settings -> Integrations -> Developer -> copy the API token into
`TODOIST_API_TOKEN`. No OAuth needed for personal use.

### 2. Calendar (Fastmail primary, iCloud optional)
**Fastmail** (recommended - simpler auth):
1. Settings -> Privacy & Security -> Integrations -> App passwords -> new
   app password, scoped to Calendar access.
2. `CALDAV_URL=https://caldav.fastmail.com/dav/calendars/user/YOUR_EMAIL/`
3. `CALDAV_USERNAME` = your Fastmail email, `CALDAV_APP_PASSWORD` = the
   password from step 1.

**iCloud** (works, but more friction - treat as a fallback):
1. appleid.apple.com -> Sign-In and Security -> App-Specific Passwords ->
   generate one. This is the known friction point: it's a separate flow
   from your normal Apple ID password and easy to forget you set up.
2. `CALDAV_URL=https://caldav.icloud.com`, `CALDAV_USERNAME` = your Apple
   ID email, `CALDAV_APP_PASSWORD` = the app-specific password.
3. Nothing else changes - `backend/pollers/calendar.py` speaks plain
   CalDAV and doesn't know or care which provider it's talking to.

### 3. Hue bridge pairing
The bridge only issues a local API key within ~30 seconds of someone
physically pressing the link button on it - this cannot be automated.

1. Find the bridge's IP (router's DHCP client list, or
   https://discovery.meethue.com/ from a machine on the same LAN).
2. Run `python3 setup/pair_hue.py <bridge-ip>`, then press the button on
   the bridge when the script tells you to.
3. Copy the printed `HUE_BRIDGE_IP` / `HUE_API_KEY` into `.env`.
4. Find which "group" (Room/Zone) ID corresponds to this room:
   `curl -sk https://<bridge-ip>/api/<key>/groups | python3 -m json.tool`
   and put its numeric ID in `config.yaml` under `hue.group_id`.

### 4. Bambu P1S local access
1. On the printer's touchscreen: Settings -> WLAN -> enable **LAN Only
   Mode**. This disables Bambu Cloud connectivity for the printer (by
   design - this project never talks to Bambu Cloud).
2. That same screen shows the **Access Code** and **Serial Number** -
   copy both into `.env` as `BAMBU_ACCESS_CODE` and `BAMBU_SERIAL`.
   `BAMBU_IP` is the printer's LAN IP (also on that screen, or your
   router's DHCP list).

> **Bambu integration status: reverse-engineered, flag before trusting.**
> Bambu has never published this protocol. `backend/pollers/bambu.py` is
> built against the local MQTT behavior documented by the community -
> primarily cross-checked against Home Assistant's `bambu_lab` integration
> and the `bambulabs_api` PyPI package. Field names and connection details
> have shifted across firmware versions before. If it doesn't connect or
> comes back empty, see the troubleshooting steps in the docstring at the
> top of `backend/pollers/bambu.py` - the short version is: verify LAN
> Only Mode + access code first, then consider swapping in
> `bambulabs_api` directly (only `bambu.py` would need to change).

## Running it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py   # reads ../config.yaml for host/port, defaults to :5000
```

Then open `http://localhost:5000` (or the Pi's IP, from another machine on
the LAN, for testing before you wire up the kiosk boot flow).

## Kiosk boot setup (Raspberry Pi OS Lite, 64-bit)

Everything under `/setup` targets a fresh Pi OS Lite image with no desktop
environment - just X, a minimal window manager, and Chromium.

1. Flash Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager,
   enabling SSH + wifi in the imager's advanced settings so you can get
   in headlessly.
2. `git clone` this repo to `~/dashboard-for-the-home` on the Pi.
3. Complete the manual steps above (`.env`, `config.yaml`, Hue pairing,
   Bambu access code, CalDAV app password) - the setup script will remind
   you but can't do these for you.
4. Run the setup script:
   ```bash
   cd ~/dashboard-for-the-home
   chmod +x setup/setup.sh
   ./setup/setup.sh
   ```
   This installs `xserver-xorg`, `xinit`, `openbox`, `chromium-browser`,
   `unclutter`; sets up the Python venv; enables console autologin on
   tty1; installs `~/.xinitrc` and appends a `startx` block to
   `~/.bash_profile`; and installs + enables two systemd units:
   - `dashboard-backend.service` (system-level) - starts the FastAPI
     backend on boot, restarts it if it dies.
   - `kiosk-chromium.service` (user-level, via `systemd --user` +
     `loginctl enable-linger`) - launches Chromium in kiosk mode pointed
     at `http://localhost:5000`, restarts it if it crashes or gets
     OOM-killed.
5. `sudo reboot`. Boot sequence from here: tty1 autologin -> `.bash_profile`
   runs `startx` -> `.xinitrc` disables screen blanking and starts
   `openbox` -> `kiosk-chromium.service` (already retrying in the
   background since boot) finds `DISPLAY :0` up and launches Chromium
   full-screen against the backend, which `dashboard-backend.service`
   started independently.

**"Flash SD card, run one script, done"** is the goal for future room
installs - clone the SD card image or repeat steps 1-5 with a new
`config.yaml` (different room name, different Hue group ID) and a new
`.env` (same integration structure, this room's Bambu printer if any).

### What the setup script does *not* automate
- Raspberry Pi Imager / initial wifi+SSH setup (step 1) - do this once
  per SD card in the Imager's UI.
- Everything in [Manual one-time setup steps](#manual-one-time-setup-steps).

## Notes on scope (v1)

- **Multi-room**: not built as a multi-tenant system - each Pi runs one
  instance of this dashboard for one room, configured via that Pi's
  `config.yaml`/`.env`. The code just avoids hardcoding room/printer
  identity so a second install is "clone repo, fill in new config," not
  a rewrite.
- **Auth / remote access**: intentionally none. The dashboard binds to
  `0.0.0.0:5000` for LAN convenience during setup/debugging, but nothing
  about it is designed to be exposed past the LAN.
- **Bambu Cloud**: never used. Local MQTT (LAN Only Mode) only, by design.
