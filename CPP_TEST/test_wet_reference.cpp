#include "brush_wet.h"
#include "wet_kernel.h"
#include "wet_mask.h"
#include <QImage>
#include <cassert>
#include <cstring>

int main(){
    QImage im(13,13,QImage::Format_RGBA8888);
    for(int y=0;y<im.height();++y) for(int x=0;x<im.width();++x)
        im.setPixelColor(x,y,QColor((x*17+y*3)&255,(x*5+y*19)&255,(x*11+y*7)&255,255));

    const auto mask=creative_wet::makeMask(3);
    creative_wet::Accum reference{}, sse{}, avx{};
    const uint8_t* center=im.constScanLine(6)+6*4;
    creative_wet::reference(center,13,13,im.bytesPerLine(),mask,reference);
    creative_wet::sse4(center,13,13,im.bytesPerLine(),mask,sse);
    creative_wet::avx2(center,13,13,im.bytesPerLine(),mask,avx);
    assert(std::memcmp(&reference,&sse,sizeof(reference))==0);
    assert(std::memcmp(&reference,&avx,sizeof(reference))==0);

    creative_wet::reset_sse4_unpack_calls();
    creative_wet::reset_avx2_unpack_calls();
    QColor c=BrushWet::sampleCanvasColorForTest(im,{6,6},10.f);
    assert(c.red()>=0&&c.red()<=255);
    assert(creative_wet::sse4_unpack_calls()>0 || creative_wet::avx2_unpack_calls()>0);
    return 0;
}
