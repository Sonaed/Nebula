"""Indexed tile reads stay nonblocking and invalidate committed-key caches."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtGui import QColor,QImage
from PySide6.QtWidgets import QApplication
from CANVAS.canvas import Canvas
from DOCUMENTS.document import Document
from DOCUMENTS.stack_program import build_stack_template


class ProjectionHotpathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.canvas=Canvas();self.canvas.set_document(Document(128,64))
        self.store=self.canvas.document.layers[0].tile_store
        image=QImage(64,64,QImage.Format.Format_ARGB32);image.fill(QColor('red'))
        self.store.set_tile(0,0,image)
        self.context=(build_stack_template(self.canvas.document),None,{self.canvas.document.layers[0].id:0})
        self.revisions=[(self.store.resident_revisions(),{})]

    def tearDown(self): self.canvas.close()

    def test_indexed_read_skips_redundant_native_queries_and_preserves_pixels(self):
        with patch.object(self.store,'has_tile',side_effect=AssertionError('duplicate query')), \
             patch.object(self.store,'tile_is_resident',side_effect=AssertionError('duplicate query')):
            program,pending=self.canvas._native_tile_program(0,0,self.context,self.revisions)
            self.assertFalse(pending)
            self.assertEqual(program.ops[0].image.pixelColor(0,0),QColor('red'))
            empty,pending=self.canvas._native_tile_program(1,0,self.context,self.revisions)
            self.assertFalse(pending)
            self.assertIsNone(empty.ops[0].image)

    def test_tile_evicted_after_indexing_is_requested_without_loading_on_ui_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            self.store.set_scratch_directory(Path(directory))
            self.assertGreater(self.store.evict_tile_to_scratch(0,0),0)
            with patch.object(self.store,'tile',side_effect=AssertionError('blocking load')), \
                 patch.object(self.store,'request_tile_async',return_value=True) as request:
                _program,pending=self.canvas._native_tile_program(0,0,self.context,self.revisions)
                self.assertTrue(pending)
                request.assert_called_once()

    def test_resident_key_cache_tracks_projection_mutations(self):
        canvas=self.canvas
        canvas.visible_document_tile_keys=lambda *args:{(0,0),(1,0)}
        with patch.object(canvas,'_publish_projection_frame',return_value=False), \
             patch.object(canvas.projection_store,'resident_keys',wraps=canvas.projection_store.resident_keys) as keys:
            canvas._ensure_projection();canvas._ensure_projection()
            self.assertEqual(keys.call_count,1)
            image=QImage(64,64,QImage.Format.Format_ARGB32);image.fill(QColor('blue'))
            canvas.projection_store.set_tile(0,0,image)
            canvas._ensure_projection()
            self.assertEqual(keys.call_count,2)

if __name__=='__main__':unittest.main()
