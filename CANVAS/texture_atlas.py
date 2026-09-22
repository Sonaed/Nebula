from dataclasses import dataclass

from CORE.native_bridge import NativeTextureAtlasHandle, load_creative_core


@dataclass(frozen=True)
class AtlasRect: x:int; y:int; w:int; h:int
class TextureAtlas:
    """Qt adapter for the native CreativeCore shelf-packed RGBA atlas."""
    def __init__(self,size=2048,padding=1):
        self.size=size; self.padding=padding; self.rects={}
        library = load_creative_core()
        self._native = NativeTextureAtlasHandle(library, size, padding) if library else None
        self.upload_count=0; self.last_upload=None; self.upload_backend=None
    def upload_region(self,key,image,backend=None,format="RGBA8888",data=None):
        if format in ("BC4", "BC7"):
            if data is None or len(data) < ((image.width + 3)//4)*((image.height + 3)//4)*(8 if format == "BC4" else 16):
                return False
            if backend is not None: backend(data, self.rects.get(key), format)
            self.upload_count += 1; self.last_upload=(self.rects.get(key).x if key in self.rects else 0,self.rects.get(key).y if key in self.rects else 0,image.width,image.height,format); return True
        r=self.add(key,image) if key not in self.rects else self.rects[key]
        if r is None:return False
        from PySide6.QtGui import QImage
        source = image.convertToFormat(QImage.Format.Format_RGBA8888)
        if not self._native or not self._native.write(r.x, r.y, source):
            return False
        self.upload_count+=1; self.last_upload=(r.x,r.y,r.w,r.h,"RGBA8888")
        if backend is not None: backend(source,r)
        return True
    def add(self,key,image):
        w,h=image.width(),image.height()
        if not self._native:return None
        position = self._native.add(w,h)
        if position is None:return None
        r=AtlasRect(position[0],position[1],w,h); self.rects[key]=r; return r
    def uv(self,key):
        r=self.rects[key]; s=float(self.size); return (r.x/s,r.y/s,(r.x+r.w)/s,(r.y+r.h)/s)
    def close(self):
        if self._native:
            self._native.close(); self._native=None
    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
