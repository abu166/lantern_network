# lantern_network
Know what’s connected. Notice what changes. Make yourself at home.

Lantern is a local network discovery dashboard with device labels, watches,
alerts, router lease imports, and persistent history.

## Run

Requires Python 3.10+; no dependencies to install.

```sh
cd lantern-network
python3 -m backend.server
```

Open **http://localhost:8765**.

See the [application guide](lantern-network/README.md) for live scanning,
tests, and macOS/Linux background-service installation.

## Availability and hosting

Run Lantern's background service on a computer connected to the network you
want to monitor. On macOS it starts after login and remains available while
the computer is awake. A Raspberry Pi or home server can provide continuous
operation; the application guide includes a private SSH tunnel for access.

The current application cannot be deployed unchanged to Vercel: discovery
requires access to your local network, and history needs a persistent SQLite
file. A remotely hosted version would require an authenticated local collector
and a persistent hosted data store. Do not publish this localhost server through
port forwarding or a public reverse proxy.
