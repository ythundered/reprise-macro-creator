import os
import unittest
from unittest import mock

from reprise import paths


class PathTests(unittest.TestCase):
    def test_source_runs_leave_the_environment_alone(self):
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/x"}):
            self.assertEqual(paths.clean_env()["LD_LIBRARY_PATH"], "/x")

    @unittest.skipIf(os.name == "nt", "linux only")
    def test_frozen_runs_restore_the_system_library_path(self):
        with mock.patch.object(paths, "FROZEN", True):
            with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/sys"}):
                self.assertEqual(paths.clean_env()["LD_LIBRARY_PATH"], "/sys")
            with mock.patch.dict(os.environ, {"FONTCONFIG_FILE": "/bundle/fonts.conf"}):
                self.assertNotIn("FONTCONFIG_FILE", paths.clean_env())
            env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH_ORIG"}
            with mock.patch.dict(os.environ, dict(env, LD_LIBRARY_PATH="/bundle"), clear=True):
                self.assertNotIn("LD_LIBRARY_PATH", paths.clean_env())

    def test_missing_tool(self):
        self.assertEqual(paths.find_tool("no-such-tool-here"), (None, None))
