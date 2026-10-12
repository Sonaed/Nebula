import unittest

from DOCUMENTS.color_management import ColorProfile, SoftProofSettings


class Phase3APITests(unittest.TestCase):
    def test_color_profile_rejects_invalid_icc(self):
        with self.assertRaises(ValueError):
            ColorProfile("bad", b"not-an-icc").validate()

    def test_soft_proof_settings_are_explicit(self):
        settings = SoftProofSettings(ColorProfile("sRGB"))
        self.assertEqual(settings.rendering_intent, "relative_colorimetric")

if __name__ == "__main__":
    unittest.main()
