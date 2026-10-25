#!/usr/bin/env python3
"""Restricted server-side entry point: immutable PULS images, fixed Compose only.

Installed root-owned at /opt/puls/bin/deploy-release.py. The SSH authorized key
forces this command and disables forwarding/PTY. Read one JSON request on stdin;
never print registry credentials or runtime environment values.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path('/opt/puls')
SERVICES = ('api', 'worker', 'frontend', 'ml', 'migrate', 'qwen')
PREFIX = 'ghcr.io/fishing-team-322/puls-'


def run(args, *, environment=None, input_data=None, timeout=300, quiet=False):
    result = subprocess.run(args, env=environment, input=input_data, stdout=subprocess.PIPE if quiet else None,
                            stderr=subprocess.PIPE if quiet else None, timeout=timeout)
    if result.returncode:
        # Captured output can include client configuration; report only the command.
        raise RuntimeError(f'{args[0]} {args[1] if len(args) > 1 else ""} failed ({result.returncode})')
    return result.stdout


def manifest_for(tag):
    saved = ROOT/'release-manifests'/(tag+'.yml')
    return saved if saved.exists() else ROOT/'compose.yml'


def has_qwen(tag):
    path=manifest_for(tag)
    return path.exists() and b'\n  qwen:\n' in path.read_bytes()


def runtime_services(tag):
    return ('ml', 'qwen', 'api', 'worker', 'frontend') if has_qwen(tag) else ('ml', 'api', 'worker', 'frontend')


def compose(tag, *args, quiet=False):
    environment = {**os.environ, 'PULS_RELEASE': tag}
    return run(['docker', 'compose', '--project-name', 'puls-production', '--env-file', str(ROOT/'runtime.env'),
                '-f', str(manifest_for(tag)), *args], environment=environment, quiet=quiet)


def wait_ready(tag, seconds=120):
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        try:
            with urlopen('http://127.0.0.1:18080/readyz', timeout=5) as response:
                ready = json.load(response)
            with urlopen('http://127.0.0.1:18080/healthz', timeout=5) as response:
                health = json.load(response)
            with urlopen('http://127.0.0.1:13000/build-info.json', timeout=5) as response:
                build = json.load(response)
            with urlopen('http://127.0.0.1:13000/v1/auth/providers', timeout=5) as response:
                json.load(response)
            if ready.get('status') == 'ready' and health.get('status') == 'ok' and health.get('ml') == 'ok' and build.get('revision') == tag:
                if has_qwen(tag):
                    compose(tag, 'exec', '-T', 'qwen', 'python', '-m', 'zavozik_ml.serving.health', '--service', 'qwen', '--address', '127.0.0.1:50054', quiet=True)
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError('New API/ML/frontend did not become ready at the requested revision')


def activate(tag):
    compose(tag, 'up', '-d', '--no-build', 'postgres')
    # The default health condition is also applied to this one-off migration.
    compose(tag, 'run', '--rm', '--no-deps', 'migrate')
    compose(tag, 'up', '-d', '--no-build', '--no-deps', *runtime_services(tag))
    wait_ready(tag)


def restore_containers(current, target):
    if has_qwen(current) and not has_qwen(target):
        compose(current, 'stop', 'qwen')
    compose(target, 'up', '-d', '--no-build', '--no-deps', *runtime_services(target))
    wait_ready(target)


def manual_rollback(tag, current):
    retained = ROOT/'previous-release'
    target = retained.read_text().strip() if retained.exists() else None
    if tag != target or tag == current or not current or not re.fullmatch(r'[0-9a-f]{40}', current):
        raise ValueError('Rollback must target the retained previous release')
    # Both directions must use immutable saved topology, never today's manifest.
    for revision in (current, tag):
        if not (ROOT/'release-manifests'/(revision+'.yml')).is_file():
            raise RuntimeError('Rollback requires saved current and previous release manifests')
    compose(tag, 'config', '--quiet')
    for service in runtime_services(tag):
        run(['docker', 'image', 'inspect', PREFIX+service+':'+tag], quiet=True)
    try:
        restore_containers(current, tag)
    except Exception:
        restore_containers(tag, current)
        raise
    # Publish pointers only after target readiness; replace each file atomically.
    for name, revision in (('previous-release', current), ('current-release', tag)):
        temporary = ROOT/(name+'.tmp')
        temporary.write_text(revision+'\n')
        temporary.replace(ROOT/name)
    print(f'PULS rolled back and healthy: {tag}', flush=True)


def main():
    os.umask(0o077)
    request = json.loads(sys.stdin.buffer.read(32769))
    tag = request.get('release', '')
    if not re.fullmatch(r'[0-9a-f]{40}', tag):
        raise ValueError('release must be a full Git commit SHA')
    expected = request.get('compose_sha256')
    actual = hashlib.sha256((ROOT/'compose.yml').read_bytes()).hexdigest()
    if expected != actual:
        raise ValueError('Production Compose differs from the reviewed infrastructure; update it explicitly')
    probe_only=request.get('probe_only',False)
    if not isinstance(probe_only,bool):raise ValueError('probe_only must be boolean')
    rollback=request.get('rollback',False)
    if not isinstance(rollback,bool):raise ValueError('rollback must be boolean')
    if rollback and probe_only:raise ValueError('rollback and probe_only are mutually exclusive')
    token = request.get('registry_token', '')
    if not isinstance(token, str) or '\n' in token or len(token) > 16384:
        raise ValueError('Invalid registry token')
    registry_user = request.get('registry_user', 'github-actions')
    if not isinstance(registry_user, str) or not re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,100}', registry_user):
        raise ValueError('Invalid registry username')
    with (ROOT/'deployment.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous_file = ROOT/'current-release'
        previous = previous_file.read_text().strip() if previous_file.exists() else None
        if rollback:
            manual_rollback(tag, previous)
            return
        if not probe_only and previous and b'\n  qwen:\n' in (ROOT/'compose.yml').read_bytes() and not (ROOT/'release-manifests'/(previous+'.yml')).exists():
            raise RuntimeError('Seed the previous release manifest before upgrading production infrastructure')
        print(f'Preparing PULS {tag}', flush=True)
        if token:
            with tempfile.TemporaryDirectory(prefix='puls-registry-', dir=ROOT) as auth:
                env = {**os.environ, 'DOCKER_CONFIG': auth}
                run(['docker', 'login', 'ghcr.io', '--username', registry_user, '--password-stdin'],
                    environment=env, input_data=token.encode(), quiet=True)
                for service in (('qwen',) if probe_only else SERVICES):
                    run(['docker', 'pull', PREFIX+service+':'+tag], environment=env, quiet=True)
        if probe_only:
            run(['docker','image','inspect',PREFIX+'qwen:'+tag],quiet=True)
            run(['python3',str(ROOT/'bin'/'probe-qwen.py'),tag],timeout=480)
            return
        for service in SERVICES:
            run(['docker', 'image', 'inspect', PREFIX+service+':'+tag], quiet=True)
        free = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
        if free < 2 * 1024**3:
            raise RuntimeError('Less than 2 GiB free; refusing deployment without touching other projects')
        manifests=ROOT/'release-manifests'
        manifests.mkdir(exist_ok=True)
        snapshot=manifests/(tag+'.yml')
        reviewed=(ROOT/'compose.yml').read_bytes()
        if snapshot.exists() and snapshot.read_bytes()!=reviewed:raise RuntimeError('Release manifest is immutable')
        snapshot.write_bytes(reviewed)
        compose(tag, 'config', '--quiet')
        compose(tag, 'up', '-d', '--no-build', 'postgres')
        for _ in range(60):
            try:
                compose(tag, 'exec', '-T', 'postgres', 'pg_isready', '-U', 'puls', '-d', 'puls', quiet=True)
                break
            except RuntimeError:
                time.sleep(2)
        else:
            raise RuntimeError('Production PostgreSQL is not ready')
        backup_dir = ROOT/'backups'
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir/(time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())+'-'+tag[:12]+'.dump')
        with backup.open('wb') as output:
            env = {**os.environ, 'PULS_RELEASE': tag}
            result = subprocess.run(['docker', 'compose', '--project-name', 'puls-production', '--env-file', str(ROOT/'runtime.env'),
                '-f', str(ROOT/'compose.yml'), 'exec', '-T', 'postgres', 'pg_dump', '-U', 'puls', '-d', 'puls', '-Fc'],
                env=env, stdout=output, timeout=120)
            if result.returncode:
                raise RuntimeError('Database backup failed')
        try:
            activate(tag)
        except Exception:
            if previous and re.fullmatch(r'[0-9a-f]{40}', previous):
                print(f'Health check failed; restoring PULS containers {previous}', flush=True)
                if has_qwen(tag) and not has_qwen(previous):
                    compose(tag, 'stop', 'qwen')
                compose(previous, 'up', '-d', '--no-build', '--no-deps', *runtime_services(previous))
                wait_ready(previous)
            raise
        if previous and previous != tag:
            (ROOT/'previous-release').write_text(previous+'\n')
        temporary = ROOT/'current-release.tmp'
        temporary.write_text(tag+'\n')
        temporary.replace(previous_file)
        # Only this application's old database dumps; no global Docker cleanup.
        for stale in sorted(backup_dir.glob('*.dump'), reverse=True)[10:]:
            stale.unlink()
        print(f'PULS deployed and healthy: {tag}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Deploy failed: {error}', file=sys.stderr)
        sys.exit(1)
