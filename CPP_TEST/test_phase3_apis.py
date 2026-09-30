import unittest

from DOCUMENTS.color_management import ColorProfile, SoftProofSettings
from CORE.scripting import (API_VERSION, ScriptDocument, ScriptPermissionError,
                            ScriptPermissions, run_script)


class Phase3APITests(unittest.TestCase):
    def test_color_profile_rejects_invalid_icc(self):
        with self.assertRaises(ValueError):
            ColorProfile("bad", b"not-an-icc").validate()

    def test_soft_proof_settings_are_explicit(self):
        settings = SoftProofSettings(ColorProfile("sRGB"))
        self.assertEqual(settings.rendering_intent, "relative_colorimetric")

    def test_script_facade_exposes_document_contract(self):
        class Layer:
            def __init__(self, name):
                self.name, self.id = name, name
                self.visible, self.opacity, self.blend_mode = True, 1.0, "normal"
        class Document:
            width, height = 64, 32
            layers = [Layer("Background")]
        called = []
        doc = ScriptDocument(Document(), lambda: called.append(True) or True,
                             permissions=ScriptPermissions(save_document=True))
        self.assertEqual(API_VERSION, "nebula.script.v1")
        self.assertEqual(run_script(lambda value: value.size, doc.document), (64, 32))
        self.assertEqual(doc.layers()[0]["name"], "Background")
        self.assertTrue(doc.save())
        self.assertTrue(called)

    def test_script_permissions_default_to_read_only(self):
        class Document:
            width, height, layers = 3, 2, []
        facade = ScriptDocument(Document())
        with self.assertRaises(ScriptPermissionError):
            facade.save()
        with self.assertRaises(ScriptPermissionError):
            facade.add_layer("Interdit")

    def test_script_can_create_retouch_layer_with_explicit_grant(self):
        from DOCUMENTS.document import Document
        document = Document(16, 16)
        facade = ScriptDocument(document, permissions=ScriptPermissions(modify_document=True))
        identifier = facade.add_retouch_layer("Corrections")
        self.assertEqual(next(layer for layer in document.layers if layer.id == identifier).layer_kind,
                         "retouch")


if __name__ == "__main__":
    unittest.main()
