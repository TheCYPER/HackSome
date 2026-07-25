"""Pytest-owned Build gate, excluded from the root unittest discovery gate."""


def load_tests(loader, tests, pattern):
    return tests
