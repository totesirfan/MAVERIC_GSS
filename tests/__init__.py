"""Tests package marker.

`unittest discover -s tests` requires this file so the directory is
importable. Side effect: makes `tests` a package, which would normally
break the flat-import pattern used by `ops_test_support` and the
gitignored `test_maveric_*` suite (`from ops_test_support import …`).
Insert this directory on `sys.path` so those flat imports keep
resolving without forcing every test file to use the dotted form.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
