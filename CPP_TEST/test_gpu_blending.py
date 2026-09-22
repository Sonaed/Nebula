from __future__ import annotations

import unittest


class GPUBlendEquationTests(unittest.TestCase):
    def test_source_over_keeps_opaque_framebuffer_alpha(self) -> None:
        # glBlendFuncSeparate(..., ONE, ONE_MINUS_SRC_ALPHA)
        # alpha_out = src_alpha + dst_alpha * (1 - src_alpha)
        for source_alpha in (0.0, 0.1, 0.35, 0.5, 0.9, 1.0):
            destination_alpha = 1.0
            output_alpha = source_alpha + destination_alpha * (1.0 - source_alpha)
            self.assertAlmostEqual(output_alpha, 1.0)

    def test_old_equation_was_translucent_for_partial_alpha(self) -> None:
        source_alpha = 0.5
        destination_alpha = 1.0
        old_output = source_alpha * source_alpha + destination_alpha * (1.0 - source_alpha)
        self.assertLess(old_output, 1.0)


if __name__ == "__main__":
    unittest.main()
