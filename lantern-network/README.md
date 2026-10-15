# Lantern

Your network, in the clear. A local-first device discovery dashboard with separate demo and live workspaces, editable device labels, recognition controls, rooms and notes, device watches, alerts, scan scheduling, router lease snapshots, history, and JSON exports.

## Run

Requires **Python 3.10+**. No package installation, API keys, or router credentials required.

```sh
cd lantern-network
python3 -m backend.server
```

Open **http://localhost:8765**. Stop with Ctrl+C. Use `--port 8766` to choose another port.

The first workspace contains clearly labeled sample devices. To discover real devices:

1. Connect this computer to your Wi-Fi or Ethernet network.
2. In **Settings**, select **Live** mode and a directly attached local subnet.
3. Save, then click **Scan network**. A /24 scan generally takes up to about 20 seconds; scheduling is optional.
4. Open a device to name it, assign its type, and mark whether you recognize it.

Live discovery supports **macOS** (`ifconfig`, `arp`, `ping`) and **Linux** (`ip` from iproute2, `ping` from iputils). No root access required. Windows can display demo mode; native discovery is not implemented. Discovery supports private IPv4 subnets /24–/30, with at most 254 targets and 32 concurrent probes. Larger local networks are narrowed to the host's /24 by default. VPN interfaces are excluded by common interface-name prefixes; check your chosen interface before scanning.

## How it works

```text
Browser UI (HTML / CSS / JavaScript)
       │ same-origin JSON API, polling every 2.5s
       ▼
Loopback HTTP server ── SQLite repository
       │                    └─ devices, scans, events, settings
       ▼
Single scan coordinator / optional scheduler
       │
Bounded ping workers ── system neighbor table
```

- `backend/scanner.py`: discovers interfaces, validates the scan boundary, pings hosts, reads available MAC addresses. Commands use argument arrays without a shell.
- `backend/store.py`: parameterized SQL, transactions, MAC-based identity with IP fallback, labels, trust decisions, and event retention (5,000 events / 2,000 scans).
- `backend/router.py`: read-only dnsmasq lease parsing, expiration and subnet filtering, stale-source detection, and hostname enrichment. Lease records do not create online sightings.
- `scripts/service.py`: generates per-user macOS launchd / Linux systemd service files without installing them.
- `backend/server.py`: HTTP API, strict local Host / Origin checks, static file allowlist, one scan at a time, worker lifecycle, settings validation. Listens only on 127.0.0.1.
- `web/`: responsive UI, hash navigation, device filtering/search, detail dialog, local settings, accessibility, and data export. No external runtime resources.
- `tests/`: temporary-database tests for persistence, discovery boundaries, and API behavior.

Data lives in `data/lantern.sqlite3` (ignored by Git). Override with `--db /path/to/file.sqlite3` or `LANTERN_DB`. Demo and live identities are separated. Scheduled scans reset to manual on restart unless you explicitly enable **Resume this schedule when Lantern starts**. A background service can be installed using the generated files below; ordinary startup does not install one. Existing databases migrate automatically without discarding labels or history. A failed scan does not mark devices unseen.

## Honest limits

This is **best-effort network discovery**, not an authoritative router client list. A sleeping device, client isolation, or a firewall can prevent ping responses. “Seen” means a host responded in the latest scan (or is the scanning host); “Not seen” means it did not respond, not necessarily that it disconnected. Events record observations at scan time, not exact connection times. Old neighbor-cache entries alone do not imply a device is online.

Hostnames are auto-filled for the scanning computer and from a fresh matching router lease when configured; assign friendly names and types yourself. Other devices initially appear as unrecognized. MAC randomization, missing neighbor records, and IP reassignment can change identity or make IP-only records ambiguous. Trust is your label, not a security verdict. The UI topology is illustrative and does not inspect the router's actual routing tree.

Lantern cannot read browsing history, measure device bandwidth, identify every device manufacturer, block clients, or monitor the whole internet. Only scan your own network or one you have permission to monitor.

This server is designed for personal localhost use. Do not expose it through port forwarding or a public reverse proxy. A hosted deployment would need an authenticated local collector; this repository intentionally keeps discovery and data local. HTTP implementation uses Python's [standard library server](https://docs.python.org/3/library/http.server.html), with [SQLite](https://docs.python.org/3/library/sqlite3.html) and [ipaddress](https://docs.python.org/3/library/ipaddress.html).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/state` | Current workspace, devices, events, scans, interfaces, scan status |
| POST | `/api/scan` | Queue one scan; 409 if a scan is running |
| PATCH | `/api/settings` | Mode, subnet, interval (0 / 60 / 300 seconds), `alert_new`, `resume_schedule` |
| PATCH | `/api/devices/:id` | Label, type, recognition, `room`, `notes`, `watched`, `miss_threshold` (1–10) |
| POST | `/api/alerts/ack` | Mark specified `ids` read, or all current-scope alerts when omitted |
| POST | `/api/alerts/claim` | Atomically claim pending desktop notifications for the current workspace |
| POST | `/api/router/import` | Import `{ "text": "..." }` as an in-memory dnsmasq lease snapshot |
| POST | `/api/router/refresh` | Refresh the configured read-only lease file |
| GET | `/api/export` | Downloadable workspace snapshot |

Mutation requests require `X-Lantern: 1` and a local same-origin request. API errors use JSON `{ "error": "..." }`.

## Verify

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
node --test tests/notifications.test.cjs
```

## Put it to use

1. In **Devices**, open a device and give it a friendly name, room, and notes. Search includes notes and rooms; use the room selector or **Watched** tab to narrow the inventory.
2. Turn on **Watch this device** for an important printer, server, or smart-home hub. The default threshold is **two consecutive successful scans that miss it**; choose 1–10. A failed scan does not advance the counter. Each missing episode creates one alert, followed by one recovery alert when the device responds again. Changing watch settings resets its counter.
3. In **Settings**, choose a scan schedule. For continued monitoring after restart, also select **Resume this schedule when Lantern starts** and save.
4. **Alerts** is a persistent inbox. The first scan on a subnet establishes the baseline; new devices discovered in later scans raise alerts if enabled. Your existing v1 scan history counts as the baseline. Demo and live alerts stay separate. The latest 1,000 alerts are retained globally.
5. Optionally click **Enable desktop notifications** in Settings and grant your browser permission. This is a per-browser opt-in, never requested automatically. One digest replaces a burst of alerts. Multiple tabs share a transactional delivery claim to prevent duplicates.

Desktop notification delivery requires a supported browser and an **open Lantern tab** (it may be in the background). Browser throttling, OS settings, and tab closure can delay or prevent delivery. The server records alerts while the browser is closed; review them on your next visit. Desktop claims are at-most-once: if a tab closes after claiming an alert, its desktop notification can be missed, but the inbox retains it. Marking an alert read also suppresses its pending desktop notification. This does not include email, phone push, or remote notifications. See [Notifications API behavior](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API/Using_the_Notifications_API).

## Router connection: dnsmasq lease bridge

The implemented adapter reads **dnsmasq-compatible IPv4 lease files**, used by compatible OpenWrt setups and other dnsmasq DHCP servers. This is a read-only file/snapshot integration, not universal router-admin login. Routers with different export formats or proprietary APIs need a model-specific adapter. No router credentials are stored.

For a quick import, switch to live mode and paste an exported lease snapshot into **Settings → Router lease connection**. Expected row format:

```text
expiry_unix_seconds MAC IPv4 hostname client-id
```

The expiry is an integer Unix timestamp; `0` represents no expiry. A hostname of `*` means unavailable. Only unexpired leases in the selected subnet are shown. Invalid rows are skipped with a count; wholly invalid snapshots are rejected. Manual imports live in memory until restart and become stale after 10 minutes. The UI always labels leases separately from responding devices.

For ongoing integration, arrange a read-only local copy of your router's lease file (for example, a file you already synchronize through your router's supported export mechanism), then start:

```sh
python3 -m backend.server --leases-file /absolute/path/to/dhcp.leases
```

Lantern reads this file on startup in live mode, before each live scan, and on **Refresh lease file**. Keep the copy synchronized and update it atomically to avoid partially written snapshots. A file older than 10 minutes is marked stale and is not used for new hostname enrichment. The dashboard shows the last read time; expired rows are removed even between refreshes. Learned device names can remain in inventory as last-known names. Lease matching requires both MAC and IP, and never turns an unresponsive lease holder into an online device. A missing or malformed lease source does not stop ping discovery. When a file is configured, pasted imports are disabled.

The adapter follows the [dnsmasq lease implementation](https://raw.githubusercontent.com/imp/dnsmasq/master/src/lease.c) and its [DHCP configuration documentation](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html).

## Always-on setup

Generate service files **on the computer that will run Lantern**, using that machine's Python interpreter and project path. The generator writes reviewable files in `deploy/`; it does not install or start a service. Files contain local paths and are ignored by Git. Add `--leases-file /absolute/path/to/dhcp.leases` to the generator if using the router bridge.

First run normally, choose a schedule, enable **Resume this schedule when Lantern starts**, and save. Stop the foreground server before starting a background service on the same port. Without resume enabled, the service serves the dashboard but scheduled monitoring remains off after restart.

### macOS: run after login

```sh
python3 scripts/service.py --platform macos
plutil -lint deploy/local.lantern.network.plist
mkdir -p "$HOME/Library/LaunchAgents"
cp deploy/local.lantern.network.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.lantern.network.plist"
```

Check status and stop it:

```sh
launchctl print "gui/$(id -u)/local.lantern.network"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.lantern.network.plist"
```

The login agent restarts the server if it exits. It does not keep the Mac awake or run while logged out. The generated file follows Apple's [launchd job structure](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html). If macOS denies access to a project under Documents, move the project to an accessible development folder and regenerate the plist; inspect `data/service.err.log` for the reason. To prevent future login starts after stopping it, move the plist out of `~/Library/LaunchAgents/`.

### Linux / Raspberry Pi: user service

```sh
python3 scripts/service.py --platform linux
mkdir -p "$HOME/.config/systemd/user"
cp deploy/lantern.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now lantern.service
systemctl --user status lantern.service
```

This starts at user-manager startup, normally login. On your dedicated always-on host, an administrator can opt into boot-time user services with `sudo loginctl enable-linger "$USER"`. Check logs and disable the service with:

```sh
journalctl --user -u lantern.service
systemctl --user disable --now lantern.service
```

The generated unit uses [systemd service restart behavior](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml), a private file-creation mask, and no-new-privileges. Ensure `ip` and `ping` are installed. Some distributions need unprivileged ICMP configured for `ping`; if every device is missed, verify that `ping` works for the service user. Service files are generated and tested here; actual Linux/systemd startup must be verified on your target host.

For a Pi or home server, open a private SSH tunnel from your laptop (replace the destination with your own):

```sh
ssh -N -L 8765:127.0.0.1:8765 your-user@your-home-server
```

Then open `http://localhost:8765`. Use matching local and remote ports; the server checks its Host header. The server remains bound to loopback and has no public dashboard or open LAN listener.

Application logs rotate at 5 MiB with three backups when started with `--log-file`; generated services use `data/lantern.log`. Database and labels remain in `data/lantern.sqlite3`. Regenerate and reinstall the service file if the project or Python executable moves.
