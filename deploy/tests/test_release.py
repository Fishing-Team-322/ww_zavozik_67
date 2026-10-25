import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

if os.name == 'posix':
    spec = importlib.util.spec_from_file_location('release', Path(__file__).resolve().parents[1]/'deploy-release.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)


@unittest.skipUnless(os.name == 'posix', 'The deployment entry point runs on the Linux server')
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root/'compose.yml').write_bytes(b'fixed production manifest\n')
        self.old, self.new = 'a'*40, 'b'*40
        (self.root/'current-release').write_text(self.old+'\n')
        self.request = {'release': self.new, 'compose_sha256': release.hashlib.sha256((self.root/'compose.yml').read_bytes()).hexdigest()}

    def invoke(self, **patches):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(release, 'ROOT', self.root))
            stack.enter_context(patch.object(release.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(self.request).encode()))))
            stack.enter_context(patch.object(release.os, 'statvfs', return_value=SimpleNamespace(f_bavail=4*1024**3, f_frsize=1)))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for key, value in patches.items():
                stack.enter_context(patch.object(release, key, value))
            release.main()

    def test_invalid_release_and_changed_infrastructure_never_invoke_docker(self):
        from unittest.mock import Mock
        for value in ['latest', '../other-project', 'a'*39]:
            self.request['release'] = value
            docker = Mock()
            with self.assertRaises(ValueError):
                self.invoke(run=docker)
            docker.assert_not_called()
        self.request['release'] = self.new
        self.request['compose_sha256'] = 'incorrect'
        docker = Mock()
        with self.assertRaises(ValueError):
            self.invoke(run=docker)
        docker.assert_not_called()

    def test_failed_health_restores_previous_containers_and_keeps_the_release_pointer(self):
        from unittest.mock import Mock
        docker, compose = Mock(return_value=b''), Mock(return_value=b'')
        ready = Mock(side_effect=[RuntimeError('unhealthy'), None])
        with patch.object(release.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as backup:
            with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                self.invoke(run=docker, compose=compose, wait_ready=ready)
        self.assertEqual((self.root/'current-release').read_text().strip(), self.old)
        self.assertTrue(list((self.root/'backups').glob('*.dump')))
        self.assertIn('pg_dump', backup.call_args.args[0])
        compose.assert_any_call(self.old, 'up', '-d', '--no-build', '--no-deps', 'ml', 'api', 'worker', 'frontend')
        ready.assert_any_call(self.old)

    def test_success_records_both_releases_after_readiness(self):
        from unittest.mock import Mock
        ready = Mock()
        with patch.object(release.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            self.invoke(run=Mock(return_value=b''), compose=Mock(return_value=b''), wait_ready=ready)
        ready.assert_called_once_with(self.new)
        self.assertEqual((self.root/'current-release').read_text().strip(), self.new)
        self.assertEqual((self.root/'previous-release').read_text().strip(), self.old)

    def test_registry_failure_removes_temporary_auth_and_never_changes_the_running_release(self):
        token, seen = 'synthetic-registry-secret', []
        self.request.update(registry_token=token, registry_user='test-user')
        def docker(args, **kwargs):
            seen.append((args, kwargs))
            if 'pull' in args:
                raise RuntimeError('registry unavailable')
            return b''
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(RuntimeError):
            self.invoke(run=docker)
        self.assertNotIn(token, output.getvalue())
        self.assertEqual(seen[0][1]['input_data'], token.encode())
        self.assertNotIn(token, ' '.join(seen[0][0]))
        self.assertFalse(Path(seen[0][1]['environment']['DOCKER_CONFIG']).exists())
        self.assertEqual((self.root/'current-release').read_text().strip(), self.old)


if __name__ == '__main__':
    unittest.main()
