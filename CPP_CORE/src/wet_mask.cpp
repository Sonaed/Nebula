#include "wet_mask.h"
#include <cmath>
namespace creative_wet { Mask makeMask(int r){Mask m{r,{}};int rs=r*r;for(int y=-r;y<=r;++y)for(int x=-r;x<=r;++x){int d=x*x+y*y;if(d>rs)continue;float w=1.0f-std::sqrt((float)d)/std::max(1.0f,(float)r);m.samples.push_back({x,y,w});}return m;} }
