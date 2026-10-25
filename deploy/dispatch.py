"""Send a release request over host-key-pinned SSH without logging credentials."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    release = os.environ['PULS_RELEASE']
    host, user = os.environ['PULS_DEPLOY_HOST'], os.environ['PULS_DEPLOY_USER']
    if not re.fullmatch(r'[0-9a-f]{40}', release):
        raise ValueError('A full commit SHA is required')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', host) or host.startswith('-') or not re.fullmatch(r'[a-zA-Z0-9_-]+', user):
        raise ValueError('Invalid SSH destination')
    compose = Path('deploy/compose.production.yml').read_bytes().replace(b'\r\n', b'\n')
    body = json.dumps({'probe_only':os.environ.get('PULS_PROBE_ONLY')=='true','release': release, 'compose_sha256': hashlib.sha256(compose).hexdigest(),
                       'registry_user': os.environ['GITHUB_ACTOR'], 'registry_token': os.environ['GH_TOKEN']}).encode()
    with tempfile.TemporaryDirectory() as directory:
        key, known = Path(directory)/'key', Path(directory)/'known_hosts'
        key.write_text(os.environ['PULS_DEPLOY_KEY'].rstrip()+'\n')
        known.write_text(os.environ['PULS_DEPLOY_KNOWN_HOSTS'].rstrip()+'\n')
        key.chmod(0o600)
        subprocess.run(['ssh', '-i', str(key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known}', '-o', 'ConnectTimeout=20',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=8', f'{user}@{host}', 'deploy'],
            input=body, timeout=1200, check=True)


if __name__ == '__main__':
    main()
