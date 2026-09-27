#include "tile_cache.h"
#include <cassert>
int main(){creative_core::TileCache c(8);c.put({1,1},{1,2,3,4});c.put({2,2},{5,6,7,8});std::vector<unsigned char> o;assert(c.get({1,1},o)&&o[0]==1);c.put({3,3},{9,10,11,12});assert(c.bytes()<=8);return 0;}
