"""Per-protection unit-test package.

Slice ``risk-stoploss-guard`` introduces this subpackage so the new
protection ships with its own focused test module
(``test_stoploss_guard.py``) rather than appending to the now-7-cap
``test_protections.py``. Existing protections continue to live in
``../test_protections.py``; the package-style layout is the target
for future per-protection test files.
"""

from __future__ import annotations
