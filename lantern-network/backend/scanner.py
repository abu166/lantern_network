"""Bounded, shell-free IPv4 discovery for directly attached private networks."""
import concurrent.futures
import ipaddress
import platform
import re
import shutil
import socket
import subprocess
import time

PRIVATE = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def run(args, timeout=4):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return p.stdout if p.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def interfaces():
    result = []
    if platform.system() == 'Darwin':
        current = None
        for line in run(['ifconfig']).splitlines():
            m = re.match(r'^(\w+):', line)
            if m:
                current = m[1]
            m = re.search(r'inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-f]+)', line)
            if m:
                mask = str(ipaddress.IPv4Address(int(m[2], 16)))
                result.append((current, ipaddress.ip_interface(f'{m[1]}/{mask}')))
    elif platform.system() == 'Linux':
        for line in run(['ip', '-o', '-4', 'addr', 'show']).splitlines():
            m = re.search(r'^\d+:\s+(\S+)\s+inet\s+(\S+)', line)
            if m:
                result.append((m[1], ipaddress.ip_interface(m[2])))
    return [dict(name=name, ip=str(i.ip), cidr=str(i.network)) for name, i in result
            if any(i.ip in n for n in PRIVATE) and not name.startswith(('docker', 'veth', 'br-', 'utun', 'tun'))]


def validate_network(cidr, available=None):
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except (ValueError, TypeError):
        raise ValueError('Enter a valid IPv4 subnet, such as 192.168.1.0/24.')
    if network.version != 4 or not 24 <= network.prefixlen <= 30:
        raise ValueError('Choose an IPv4 subnet between /24 and /30 (at most 254 devices).')
    if not any(network.subnet_of(n) for n in PRIVATE):
        raise ValueError('Only private local networks can be scanned.')
    available = interfaces() if available is None else available
    if not any(network.subnet_of(ipaddress.ip_network(i['cidr'])) for i in available):
        raise ValueError('This subnet is not on a supported local interface. Connect to that network first.')
    return network


def arp_entries():
    output = run(['arp', '-an']) if platform.system() == 'Darwin' else run(['ip', '-4', 'neigh', 'show'])
    entries = {}
    for line in output.splitlines():
        ip = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', line)
        mac = re.search(r'\b(?:[0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2}\b', line)
        if ip and mac:
            normalized = ':'.join(part.zfill(2) for part in mac[0].lower().split(':'))
            if normalized != '00:00:00:00:00:00' and not int(normalized[:2], 16) & 1:
                entries[ip[0]] = normalized
    return entries


def ping(ip):
    start = time.monotonic()
    args = ['ping', '-n', '-c', '1', '-W', '800' if platform.system() == 'Darwin' else '1', ip]
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2)
        if p.returncode == 0:
            m = re.search(r'time[=<]([\d.]+)', p.stdout)
            return ip, round(float(m[1]) if m else (time.monotonic() - start) * 1000, 1)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ip, None


def scan(cidr):
    network = validate_network(cidr)
    if not shutil.which('ping'):
        raise RuntimeError('The system ping command is missing. Install it before scanning.')
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        answers = dict(pool.map(ping, map(str, network.hosts())))
    neighbors = arp_entries()
    own = {i['ip'] for i in interfaces()}
    devices = []
    for ip, latency in answers.items():
        # An old ARP entry alone is not proof a device is online.
        if latency is not None or ip in own:
            devices.append(dict(ip=ip, mac=neighbors.get(ip), latency=latency,
                                hostname=socket.gethostname() if ip in own else '',
                                kind='computer' if ip in own else 'device', source='local' if ip in own else 'ping'))
    return devices
