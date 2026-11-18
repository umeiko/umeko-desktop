"""Bounded DNS fallback for Ubuntu archives on an ephemeral CI runner."""
import ipaddress
import json
import subprocess
import sys
from urllib.parse import urlencode

ARCHIVES = frozenset(('archive.ubuntu.com', 'security.ubuntu.com', 'ports.ubuntu.com'))


def addresses(host, answer):
    if answer.get('Status') != 0 or answer.get('TC') or answer.get('CD'):
        raise ValueError('DNS response is unsuccessful or validation was disabled')
    if not any(q.get('name', '').rstrip('.').lower() == host and q.get('type') == 1
               for q in answer.get('Question', [])):
        raise ValueError('DNS question does not match the Ubuntu archive')
    names = {host}
    records = answer.get('Answer', [])
    for _ in range(16):
        previous = len(names)
        names.update(r['data'].rstrip('.').lower() for r in records
                     if r.get('type') == 5 and r.get('name', '').rstrip('.').lower() in names)
        if len(names) == previous:
            break
    result = []
    for record in records:
        if record.get('type') != 1 or record.get('name', '').rstrip('.').lower() not in names:
            continue
        address = ipaddress.ip_address(record['data'])
        if address.version != 4 or not address.is_global:
            raise ValueError('DNS fallback returned a non-public IPv4 address')
        if str(address) not in result:
            result.append(str(address))
    if not result:
        raise ValueError('DNS fallback returned no archive addresses')
    return result[:4]


def resolve(host):
    if host not in ARCHIVES:
        raise ValueError('DNS fallback is restricted to Ubuntu archive hosts')
    try:
        local = subprocess.run(['getent', 'ahostsv4', host], capture_output=True,
                               text=True, timeout=5)
        if local.returncode == 0 and local.stdout.strip():
            return []
    except subprocess.TimeoutExpired:
        pass
    query = urlencode({'name': host, 'type': 'A', 'cd': '0'})
    errors = []
    for provider in ('https://dns.google/resolve?', 'https://cloudflare-dns.com/dns-query?'):
        try:
            response = subprocess.run(['curl', '--http1.1', '--silent', '--show-error', '--fail',
                                      '--connect-timeout', '5', '--max-time', '20',
                                      '-H', 'Accept: application/dns-json', provider + query],
                                     check=True, capture_output=True, text=True, timeout=25)
            result = addresses(host, json.loads(response.stdout))
            print(f'Using HTTPS DNS fallback for {host}', file=sys.stderr)
            return result
        except (subprocess.SubprocessError, ValueError) as error:
            errors.append(type(error).__name__)
    raise RuntimeError(f'Both HTTPS DNS resolvers failed for {host}: {errors}')


def main(hosts):
    entries = []
    for host in hosts:
        for address in resolve(host):
            entries.append(f'{address} {host} # umeko-ci-ubuntu-dns')
    # Emit only after every requested host has resolved; the caller then installs
    # these entries temporarily. TLS hostname and apt signature checks stay on.
    if entries:
        print('\n'.join(entries))


if __name__ == '__main__':
    main(sys.argv[1:])
