import sys
import unittest.mock

from rstviewer import rstviewer


def test_runs():
    with unittest.mock.patch.object(sys, "argv", ["rstviewer", "README.rst"]):
        rstviewer.main(test_mode=True)
