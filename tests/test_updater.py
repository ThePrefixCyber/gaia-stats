"""Failure-path tests run the real shell control flow with external actions mocked."""
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch
import subprocess
import sys
import tempfile
import unittest

from gaia_stats.wsgi import Application

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_health', ROOT / 'deploy/verify-health.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class HealthVerificationTests(unittest.TestCase):
    def fetch(self, url):
        if url.endswith('/healthz'):
            return {'status': 'ok', 'commit': 'target', 'games': 2, 'player_records': 2}
        ruleset = url.split('=')[-1]
        return {'ruleset': ruleset, 'games': 1, 'player_records': 1,
                'rows': [{'game_id': ruleset, 'ruleset': ruleset}]}

    def test_verifies_both_servers_and_rulesets(self):
        calls = []
        health.verify('target', lambda url: (calls.append(url), self.fetch(url))[1])
        self.assertEqual(len(calls), 6)
        self.assertTrue(any(':8000/' in url for url in calls))
        self.assertTrue(any('127.0.0.1/' in url for url in calls))

    def test_rejects_stale_commit_missing_metadata_mixed_rulesets_and_bad_counts(self):
        for problem in ('commit', 'missing', 'ruleset', 'counts', 'health-counts'):
            def fetch(url):
                result = copy.deepcopy(self.fetch(url))
                if url.endswith('/healthz'):
                    if problem == 'commit':
                        result['commit'] = 'old'
                    if problem == 'missing':
                        return {'status': 'ok'}
                    if problem == 'health-counts':
                        result['games'] = 999
                else:
                    if problem == 'ruleset':
                        result['rows'][0]['ruleset'] = 'combined'
                    if problem == 'counts':
                        result['player_records'] = 99
                return result
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                health.verify('target', fetch)

    def test_real_wsgi_responses_and_commit_stays_at_worker_start(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('gaia_stats.wsgi.subprocess.check_output', return_value='running-sha\n'):
                app = Application(Path(folder) / 'analysis.json')
            def fetch(url):
                from urllib.parse import urlsplit
                parsed = urlsplit(url)
                statuses = []
                body = b''.join(app({'PATH_INFO': parsed.path, 'QUERY_STRING': parsed.query,
                                     'REQUEST_METHOD': 'GET'},
                                    lambda status, headers: statuses.append(status)))
                self.assertEqual(statuses, ['200 OK'])
                return json.loads(body)
            # Changing Git after worker startup must not relabel that running worker.
            with patch('gaia_stats.wsgi.subprocess.check_output', return_value='new-checkout-sha\n'):
                health.verify('running-sha', fetch)
                with self.assertRaises(ValueError):
                    health.verify('new-checkout-sha', fetch)


class UpdaterTests(unittest.TestCase):
    def run_update(self, scenario, bootstrap=False, locked=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bin').mkdir()
            (root / '.venv/bin').mkdir(parents=True)
            (root / 'deploy').mkdir()
            (root / 'deploy/verify-health.py').write_text('# mocked verifier\n')
            dataset = root / 'analysis.json'
            dataset.write_bytes(b'production-data-must-survive')
            if scenario == 'missing-data':
                dataset.unlink()
            elif scenario == 'empty-data':
                dataset.write_bytes(b'')
            before_data = dataset.read_bytes() if dataset.exists() else None
            script = (ROOT / 'deploy/update-vps.sh').read_text()
            script = script.replace('/opt/gaia-stats', folder)
            script = script.replace('/var/lib/gaia-stats/deploy-status.json', folder + '/status.json')
            script = script.replace('/var/lib/gaia-stats/analysis.json', str(dataset))
            script = script.replace('/run/lock/gaia-stats-update.lock', folder + '/lock')
            (root / 'update.sh').write_text(script)
            mock = '''#!/bin/bash
name="${0##*/}"
echo "$name $*" >> "$CALL_LOG"
case "$name" in
 git)
  case "$*" in
   'rev-parse HEAD') echo previous;;
   'rev-parse origin/main') if [[ "$SCENARIO" == unchanged* ]]; then echo previous; else echo target; fi;;
   'status --porcelain --untracked-files=no') [[ "$SCENARIO" != dirty ]] || echo ' M tracked';;
   'merge-base --is-ancestor HEAD origin/main') [[ "$SCENARIO" != divergent ]];;
   'reset --hard previous') rm -f deploy/verify-health.py; [[ "$SCENARIO" != reset-fails ]];;
  esac;;
 pip) [[ "$SCENARIO" != dependencies-fail ]];;
 runuser) [[ "$SCENARIO" != tests-fail && "$SCENARIO" != reset-fails && "$SCENARIO" != restart-fails && "$SCENARIO" != rollback-health-fails ]];;
 systemctl) [[ "$SCENARIO" != restart-fails ]];;
 python3)
  if [[ "$1" == - ]]; then exec REAL_PYTHON "$@"; fi
  test -r "$1" || exit 1
  [[ "$SCENARIO" != unchanged-unhealthy && "$SCENARIO" != rollback-health-fails && !( "$SCENARIO" == target-unhealthy && "$2" == target ) ]];;
esac
'''.replace('REAL_PYTHON', sys.executable)
            for name in ('bin/git', 'bin/runuser', 'bin/systemctl', 'bin/python3', '.venv/bin/pip'):
                path = root / name
                path.write_text(mock)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'],
                       CALL_LOG=str(root / 'calls'), SCENARIO=scenario)
            with (root / 'lock').open('w') as lock:
                if locked:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(['bash', str(root / 'update.sh')] + (['--bootstrap'] if bootstrap else []),
                                        env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(dataset.read_bytes() if dataset.exists() else None, before_data)
            status = json.loads((root / 'status.json').read_text()) if (root / 'status.json').exists() else None
            calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
            for line in calls.splitlines():
                if line.startswith('python3 /'):
                    self.assertFalse(Path(line.split()[1]).exists(), 'Temporary verifier was not cleaned up')
            return result.returncode, status, calls

    def test_no_change_checks_health_without_restart(self):
        code, status, calls = self.run_update('unchanged')
        self.assertEqual((code, status['state']), (0, 'up-to-date'))
        self.assertIn('python3 /tmp/', calls)
        self.assertNotIn('systemctl', calls)

    def test_bootstrap_tests_and_restarts_even_at_current_head(self):
        code, status, calls = self.run_update('unchanged', bootstrap=True)
        self.assertEqual((code, status['state']), (0, 'bootstrap-verified'))
        self.assertIn('pip install', calls)
        self.assertIn('runuser', calls)
        self.assertIn('systemctl restart', calls)

    def test_successful_deploy_records_target(self):
        code, status, calls = self.run_update('success')
        self.assertEqual((code, status['state'], status['target_commit']), (0, 'deployed', 'target'))
        self.assertIn('git merge --ff-only', calls)

    def test_healthy_rollback_after_failed_tests_or_wrong_commit(self):
        for scenario in ('tests-fail', 'target-unhealthy'):
            code, status, calls = self.run_update(scenario)
            self.assertEqual((code, status['state']), (1, 'rolled-back'))
            self.assertIn('git reset --hard previous', calls)
            self.assertTrue(any(line.startswith('python3 /tmp/') and line.endswith(' previous') for line in calls.splitlines()))

    def test_rollback_failures_are_not_reported_as_recovered(self):
        for scenario in ('dependencies-fail', 'restart-fails', 'rollback-health-fails', 'reset-fails'):
            with self.subTest(scenario=scenario):
                code, status, _ = self.run_update(scenario)
                self.assertEqual((code, status['state']), (1, 'rollback-failed'))

    def test_preflight_and_unchanged_health_fail_without_reset(self):
        for scenario in ('dirty', 'divergent', 'unchanged-unhealthy', 'missing-data', 'empty-data'):
            code, status, calls = self.run_update(scenario)
            self.assertEqual((code, status['state']), (1, 'failed'))
            self.assertNotIn('git reset', calls)
            self.assertNotIn('pip install', calls)

    def test_existing_lock_prevents_any_actions(self):
        code, status, calls = self.run_update('success', locked=True)
        self.assertEqual(code, 1)
        self.assertIsNone(status)
        self.assertEqual(calls, '')


class BootstrapTests(unittest.TestCase):
    def test_polling_is_enabled_only_after_successful_bootstrap(self):
        for successful in (True, False):
            with self.subTest(successful=successful), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                script = (ROOT / 'deploy/enable-updates.sh').read_text()
                script = script.replace('if [[ "${EUID}" -ne 0 ]]; then', 'if false; then')
                script = script.replace('/etc/systemd/system', folder)
                (root / 'enable.sh').write_text(script)
                for name, status in (('systemctl', 0), ('bash', 0 if successful else 1)):
                    path = root / name
                    path.write_text('#!/bin/bash\necho "' + name + ' $*" >> "$CALL_LOG"\nexit ' + str(status) + '\n')
                    path.chmod(0o755)
                result = subprocess.run(['/bin/bash', str(root / 'enable.sh')],
                                        env=dict(os.environ, PATH=folder + ':' + os.environ['PATH'],
                                                 CALL_LOG=str(root / 'calls')),
                                        capture_output=True, text=True, timeout=10)
                calls = (root / 'calls').read_text()
                self.assertIn('bash /opt/gaia-stats/deploy/update-vps.sh --bootstrap', calls)
                self.assertNotIn('restart gaia-stats', calls)
                if successful:
                    self.assertEqual(result.returncode, 0)
                    self.assertLess(calls.index('--bootstrap'), calls.index('enable --now'))
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('enable --now', calls)
