"""Unittest discovery with maintained process scheduling and explicit serial exceptions."""
import argparse
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from unittest_parallel.main import main as parallel_main

ROOT = Path(__file__).resolve().parents[1]

# Whole discovery modules only; every exception needs a one-line resource reason.
# Fix shared resources in fixtures before adding an exception here.
SERIAL_MODULES = {}


def load_module(name, pattern, filters):
    loader = unittest.TestLoader()
    loader.testNamePatterns = filters
    return loader.loadTestsFromModule(importlib.import_module(name), pattern=pattern)


class ModuleSuite(unittest.TestSuite):
    """Recreate load_tests suites in the worker, including local wrapper classes."""
    def __init__(self, suite, name, pattern, filters):
        super().__init__(suite)
        self.source = name, pattern, filters

    def __reduce__(self):
        return load_module, self.source


class ModuleLoader(unittest.TestLoader):
    def loadTestsFromModule(self, module, *args, pattern=None, **kwargs):
        suite = super().loadTestsFromModule(module, *args, pattern=pattern, **kwargs)
        return ModuleSuite(suite, module.__name__, pattern, self.testNamePatterns)


def cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from cases(test)
        else:
            yield test


def run_group(suite, jobs):
    # unittest-parallel owns process spawning, scheduling and failure reporting.
    # Supply the already-discovered suite so exceptions cannot change discovery.
    with patch.object(unittest.TestLoader, 'discover', return_value=suite):
        try:
            parallel_main(['-s', str(ROOT / 'tests'), '-v', '--level=module',
                           '--disable-process-pooling', '-j', str(jobs)])
        except SystemExit as error:
            return error.code or 0
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=0,
                        help='worker count; default: unittest-parallel uses all CPU cores')
    parser.add_argument('--pattern', default='test_*.py')
    parser.add_argument('-k', action='append', help='unittest name filter (local focused runs)')
    parser.add_argument('--list', action='store_true', help='print discovered test IDs without running')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    loader = ModuleLoader()
    if args.k:
        loader.testNamePatterns = [value if '*' in value else '*' + value + '*' for value in args.k]
    discovered = loader.discover(str(ROOT / 'tests'), pattern=args.pattern)
    if args.list:
        for test in cases(discovered):
            print(test.id())
        return 0
    parallel, serial = unittest.TestSuite(), unittest.TestSuite()
    for module in discovered:
        if not module.countTestCases():
            continue
        # Discovery's top-level suites are modules. A load_tests hook can
        # return local TestCase classes that cannot themselves be pickled.
        # Re-run that same hook in the fresh worker instead of rewriting tests.
        name = module.source[0] if isinstance(module, ModuleSuite) else next(cases(module)).id().split('.')[0]
        names = {name}
        exclusive = names.intersection(SERIAL_MODULES)
        (serial if exclusive else parallel).addTest(module)
        for name in sorted(exclusive):
            print(f'Serial: {name}: {SERIAL_MODULES[name]}', flush=True)
    print(f'Discovered {discovered.countTestCases()} tests: '
          f'{parallel.countTestCases()} parallel, {serial.countTestCases()} serial', flush=True)
    status = run_group(parallel, args.jobs) if parallel.countTestCases() else 0
    # All parallel unit workers have exited before an exclusive module starts.
    if serial.countTestCases():
        status = run_group(serial, 1) or status
    return status


if __name__ == '__main__':
    raise SystemExit(main())
