"""Independent pixel formulas and end-to-end persistence for added blend modes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from DOCUMENTS.document import Document
from DOCUMENTS.blend_mode_catalog import BLEND_MODES, BLEND_MODE_IDS
from DOCUMENTS.blend_modes import composite_layers, composite_document
from DOCUMENTS.format_psd import PSDFormat
from DOCUMENTS.layer_manager import LayerManager


def formula(mode, b, s):
    if mode in ('darker_color', 'lighter_color'):
        choose = sum(s) < sum(b) if mode == 'darker_color' else sum(s) > sum(b)
        return s if choose else b
    result = []
    for x, y in zip(b, s):
        if mode == 'linear_dodge': v = min(1, x+y)
        elif mode == 'linear_burn': v = max(0, x+y-1)
        elif mode == 'linear_light': v = min(1, max(0, x+2*y-1))
        elif mode == 'pin_light': v = min(x, 2*y) if y < .5 else max(x, 2*y-1)
        elif mode == 'hard_mix': v = float(x+y >= 1)
        elif mode == 'subtract': v = max(0, x-y)
        elif mode == 'divide': v = 1 if y == 0 else min(1, x/y)
        elif mode == 'vivid_light':
            if y < .5: v = 1 if x == 1 else 0 if y == 0 else max(0, 1-(1-x)/(2*y))
            else: v = 0 if x == 0 else 1 if y == 1 else min(1, x/(2*(1-y)))
        else: raise AssertionError(mode)
        result.append(v)
    return result


class ExtendedBlendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_native_pixels_match_independent_formulas_with_alpha_and_parameters(self):
        colors = [(0, 255, 128, 255), (255, 0, 64, 255), (49, 160, 210, 113),
                  (191, 45, 102, 0), (128, 127, 255, 197)]
        for mode in BLEND_MODES[16:]:
            for parameters in ({}, {'intensity': .71, 'mix_normal': .19, 'opposite_mix': .23, 'opacity': .81}):
                doc = Document(len(colors), len(colors))
                bottom = doc.layers[0]; top = doc.add_layer('Blend')
                top.blend_mode = mode; top.opacity = .73; top.blend_parameters = parameters
                for y, bc in enumerate(colors):
                    for x, sc in enumerate(colors):
                        bottom.image.setPixelColor(x, y, QColor(*bc)); top.image.setPixelColor(x, y, QColor(*sc))
                outputs = (composite_layers(doc.width, doc.height, doc.layers), composite_document(doc))
                for y, bc in enumerate(colors):
                    for x, sc in enumerate(colors):
                        b = [v/255 for v in bc[:3]]; s = [v/255 for v in sc[:3]]
                        ba = bc[3]/255; sa = sc[3]/255*.73*parameters.get('opacity', 1)
                        oa = sa + ba*(1-sa)
                        blend = formula(mode, b, s)
                        intensity=parameters.get('intensity',1); mix=parameters.get('mix_normal',0)
                        main=intensity*(1-mix)*(1-parameters.get('opposite_mix',0)); normal=1-intensity*(1-mix)
                        blend=[(v*main+n*normal)/(main+normal) for v,n in zip(blend,s)]
                        rgb=[(s[c]*sa*(1-ba)+blend[c]*sa*ba+b[c]*ba*(1-sa))/oa if oa else 0 for c in range(3)]
                        expected=[round(v*255) for v in rgb]+[round(oa*255)]
                        for output in outputs:
                            with self.subTest(mode=mode, params=parameters, x=x, y=y):
                                actual=output.pixelColor(x,y).getRgb()
                                self.assertLessEqual(max(abs(a-e) for a,e in zip(actual,expected)), 2)

    def test_merge_and_psd_round_trip_keep_all_added_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in BLEND_MODES[16:]:
                with self.subTest(mode=mode):
                    doc=Document(4,3);doc.layers[0].image.fill(QColor(57,168,204,255))
                    top=doc.add_layer(mode);top.image.fill(QColor(192,83,130,171));top.blend_mode=mode;top.opacity=.8
                    expected=composite_document(doc).pixelColor(0,0)
                    path=Path(directory)/(mode+'.psd')
                    self.assertTrue(PSDFormat.save(doc,path))
                    loaded=PSDFormat._load_native(path)
                    self.assertEqual(loaded.layers[1].blend_mode,mode)
                    got=composite_document(loaded).pixelColor(0,0)
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(got.getRgb(),expected.getRgb())),2)
                    self.assertTrue(LayerManager(doc).merge_down(1))
                    got=composite_document(doc).pixelColor(0,0)
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(got.getRgb(),expected.getRgb())),2)

    def test_catalog_is_shared_by_display_worker_and_native_dispatch(self):
        from CORE.native_bridge import _PARAMETER_MODE_IDS
        from CORE.projection_worker import _MODE_IDS
        from DOCUMENTS.stack_program import _MODE_IDS as stack_ids
        from UI.widgets.blend_preview import _MODE_ID, BlendPreviewWidget
        from UI.docks.layers_dock import LayersDock
        self.assertEqual(len(BLEND_MODES),26)
        for mapping in (_PARAMETER_MODE_IDS,_MODE_IDS,stack_ids,_MODE_ID): self.assertEqual(mapping,BLEND_MODE_IDS)
        dock=LayersDock(None);preview=BlendPreviewWidget()
        try:
            self.assertEqual({dock.blend_mode_combo.itemData(i) for i in range(dock.blend_mode_combo.count())},set(BLEND_MODES))
            preview.set_mode('linear_dodge')
            self.assertEqual(preview._uniform_for_key('intensity'),'intensity')
        finally:
            dock.close();preview.close()

if __name__ == '__main__': unittest.main()
