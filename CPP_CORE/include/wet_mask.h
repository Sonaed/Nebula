#pragma once
#include <vector>
namespace creative_wet { struct Sample{int dx,dy;float weight;}; struct Mask{int radius;std::vector<Sample> samples;}; Mask makeMask(int radius); }
