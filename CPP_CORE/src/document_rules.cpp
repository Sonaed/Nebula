#include "document_rules.h"

bool validateDocumentGeometry(int width, int height, int dpi,
                              int maximumDimension,
                              std::uint64_t maximumPixels)
{
    if (width <= 0 || height <= 0 || dpi < 1 || dpi > 9600 ||
        maximumDimension <= 0 || width > maximumDimension ||
        height > maximumDimension || maximumPixels == 0) return false;
    const auto pixels = static_cast<std::uint64_t>(width) *
                        static_cast<std::uint64_t>(height);
    return pixels <= maximumPixels;
}
