"""A pytest plugin that moves the REAL Python clock, to prove a test does not depend on today's date.

Load it with ``python -m pytest -p clockshift_plugin`` (this folder on PYTHONPATH) and set
``AGENTTALK_TEST_CLOCK_OFFSET_S`` to the shift in seconds (negative for the past). It shifts
``time.time``, ``time.time_ns``, ``datetime.datetime.now/utcnow/today`` and ``datetime.date.today``.
It leaves ``time.monotonic`` alone (differences stay valid) and does not reach child processes.
``tests/test_python_clock_independence.py`` is the one place that uses it.
"""
import datetime as _dt
import os
import time as _time

_RealDateTime = _dt.datetime
_OFFSET = float(os.environ.get("AGENTTALK_TEST_CLOCK_OFFSET_S", "0"))
_DELTA = _dt.timedelta(seconds=_OFFSET)

if _OFFSET:
    _real_time = _time.time
    _real_time_ns = _time.time_ns
    _time.time = lambda: _real_time() + _OFFSET
    _time.time_ns = lambda: _real_time_ns() + int(_OFFSET * 1e9)

    class _ShiftedDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _RealDateTime.now(tz) + _DELTA

        @classmethod
        def utcnow(cls):
            return _RealDateTime.utcnow() + _DELTA

        @classmethod
        def today(cls):
            return _RealDateTime.today() + _DELTA

    class _ShiftedDate(_dt.date):
        @classmethod
        def today(cls):
            return (_RealDateTime.today() + _DELTA).date()

    _dt.datetime = _ShiftedDateTime
    _dt.date = _ShiftedDate
