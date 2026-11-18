"""The CI-only archive resolver keeps TLS/GPG trust and rejects unsafe DNS data."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ci_linux_dns', Path(__file__).resolve().parents[1] / 'scripts/ci-linux-dns.py')
dns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dns)
HOST = 'archive.ubuntu.com'


def response(address='91.189.91.83'):
    return {'Status': 0, 'Question': [{'name': HOST + '.', 'type': 1}],
            'Answer': [{'name': HOST + '.', 'type': 1, 'data': address}]}


class LinuxArchiveDnsTests(unittest.TestCase):
    def test_working_system_dns_does_not_call_remote_resolver(self):
        with patch.object(dns.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'resolved', '')) as run:
            self.assertEqual(dns.resolve(HOST), [])
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_system_timeout_uses_bounded_https_with_validation(self):
        answers = [subprocess.TimeoutExpired('getent', 5),
                   subprocess.CompletedProcess([], 0, json.dumps(response()), '')]
        with patch.object(dns.subprocess, 'run', side_effect=answers) as run:
            self.assertEqual(dns.resolve(HOST), ['91.189.91.83'])
            command = run.call_args.args[0]
            self.assertIn('https://dns.google/resolve?name=archive.ubuntu.com&type=A&cd=0', command)
            self.assertNotIn('--insecure', command)
            self.assertIn('--max-time', command)
            self.assertEqual(run.call_args.kwargs['timeout'], 25)

    def test_rejects_wrong_questions_errors_and_non_public_addresses(self):
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '198.18.0.1', '::1'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                dns.addresses(HOST, response(address))
        for field, value in [('Status', 2), ('TC', True), ('CD', True), ('Question', [])]:
            answer = response(); answer[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                dns.addresses(HOST, answer)
        with self.assertRaises(ValueError):
            dns.resolve('example.com')

    def test_first_resolver_failure_uses_one_independent_fallback(self):
        answers = [subprocess.CompletedProcess([], 2, '', ''),
                   subprocess.CompletedProcess([], 0, json.dumps({'Status': 2}), ''),
                   subprocess.CompletedProcess([], 0, json.dumps(response()), '')]
        with patch.object(dns.subprocess, 'run', side_effect=answers) as run:
            self.assertEqual(dns.resolve(HOST), ['91.189.91.83'])
            self.assertIn('https://cloudflare-dns.com/dns-query?', run.call_args.args[0][-1])
            self.assertEqual(run.call_count, 3)

    def test_both_resolvers_failing_stops_after_the_bounded_attempts(self):
        answers = [subprocess.CompletedProcess([], 2, '', ''),
                   subprocess.CompletedProcess([], 0, json.dumps({'Status': 2}), ''),
                   subprocess.CalledProcessError(6, 'curl')]
        with patch.object(dns.subprocess, 'run', side_effect=answers) as run:
            with self.assertRaises(RuntimeError):
                dns.resolve(HOST)
            self.assertEqual(run.call_count, 3)

    def test_valid_aliases_work_and_unrelated_answers_are_ignored(self):
        answer = response(); answer['Answer'] = [
            {'name': HOST + '.', 'type': 5, 'data': 'mirror.example.'},
            {'name': 'mirror.example.', 'type': 1, 'data': '91.189.91.83'},
            {'name': 'unrelated.example.', 'type': 1, 'data': '127.0.0.1'}]
        self.assertEqual(dns.addresses(HOST, answer), ['91.189.91.83'])

    def test_failure_emits_no_partial_hosts_file(self):
        output = io.StringIO()
        with patch.object(dns, 'resolve', side_effect=[['91.189.91.83'], ValueError('unavailable')]), contextlib.redirect_stdout(output):
            with self.assertRaises(ValueError):
                dns.main([HOST, 'security.ubuntu.com'])
        self.assertEqual(output.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
