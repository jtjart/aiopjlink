import unittest

import aiopjlink
import aiopjlink.projector as legacy


class LegacyModuleTests(unittest.TestCase):
    """`aiopjlink.projector` still exports everything it used to."""

    def test_legacy_names_are_the_public_objects(self):
        for name in legacy.__all__:
            self.assertIs(getattr(legacy, name), getattr(aiopjlink, name), name)

    def test_public_names_are_all_available_from_the_legacy_module(self):
        public = set(aiopjlink.__all__) - {"__version__"}
        self.assertEqual(public, set(legacy.__all__))
