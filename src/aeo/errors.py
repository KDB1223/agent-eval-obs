"""Errors that the CLI maps to exit codes."""


class AeoError(Exception):
    """Base error. Subclasses set ``exit_code``."""

    exit_code = 1


class UsageError(AeoError):
    """Bad arguments, missing config, or an unknown run id."""

    exit_code = 2


class SuiteError(AeoError):
    """A task file is missing a field or breaks a suite invariant."""

    exit_code = 2


class RunError(AeoError):
    """A saved run cannot be read."""

    exit_code = 1
