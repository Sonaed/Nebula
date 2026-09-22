#pragma once

#include <cstdint>

// Shared document raster and resolution limits. Kept independent of UI models.
bool validateDocumentGeometry(int width, int height, int dpi,
                              int maximumDimension = 100000,
                              std::uint64_t maximumPixels = 64ull * 1024 * 1024);
