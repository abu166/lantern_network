"""Generate reviewable per-user background services without installing anything."""
import argparse
from pathlib import Path
import plistlib
import sys

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'local.lantern.network'
PATH = '/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin'


def systemd_quote(value, expand=False):
    value = str(value)
    if '\n' in value or '\r' in value or '\0' in value:
        raise ValueError('Service paths must not contain newlines or null characters.')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if expand:
        value = value.replace('$', '$$')
    return '"' + value + '"'


def generate(target, root=ROOT, python=sys.executable, port=8765, leases_file=None):
    root = Path(root).resolve()
    args = [str(Path(python).resolve()), '-m', 'backend.server', '--port', str(port),
            '--db', str(root/'data'/'lantern.sqlite3'), '--log-file', str(root/'data'/'lantern.log')]
    if leases_file:
        args += ['--leases-file', str(Path(leases_file).expanduser().resolve())]
    if target == 'macos':
        return LABEL+'.plist', plistlib.dumps(dict(Label=LABEL, ProgramArguments=args,
            WorkingDirectory=str(root), RunAtLoad=True, KeepAlive=True, ThrottleInterval=15,
            ProcessType='Background', EnvironmentVariables=dict(PATH=PATH),
            StandardOutPath=str(root/'data'/'service.out.log'),
            StandardErrorPath=str(root/'data'/'service.err.log')))
    if target != 'linux':
        raise ValueError('Choose macos or linux.')
    unit = f'''[Unit]
Description=Lantern local network monitor
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory={systemd_quote(root)}
ExecStart={' '.join(systemd_quote(arg, expand=True) for arg in args)}
Environment="PATH={PATH}"
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
'''
    return 'lantern.service', unit.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=['macos','linux'], required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'deploy')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--leases-file')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port from 1024 to 65535.')
    (ROOT/'data').mkdir(exist_ok=True)
    name, content = generate(args.platform, port=args.port, leases_file=args.leases_file)
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / name
    output.write_bytes(content)
    print(f'Generated {output}\nNothing installed. Review this file, then follow README instructions to enable it.')


if __name__ == '__main__':
    main()
