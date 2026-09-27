#include "brush_random.h"

float BrushRandom::range(
    unsigned int& state,
    float minimum,
    float maximum
)
{
    state =
        1664525u * state +
        1013904223u;

    const float normalized =
        static_cast<float>(state) /
        static_cast<float>(0xFFFFFFFFu);

    return minimum +
        (maximum - minimum) *
        normalized;
}
