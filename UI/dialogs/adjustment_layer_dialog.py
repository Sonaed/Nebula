from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QSpinBox, QVBoxLayout, QWidget
from UI.theme.palette import COLORS

class CurveEditor(QWidget):
    changed = Signal()
    colors = {"rgb": COLORS["curve_rgb"], "red": COLORS["curve_red"], "green": COLORS["curve_green"], "blue": COLORS["curve_blue"]}
    def __init__(self, curves, parent=None):
        super().__init__(parent); self.setMinimumSize(300, 230); self.curves={k:[list(p) for p in v] for k,v in curves.items()}; self.channel="rgb"; self.drag=None
        for key in self.colors: self.curves.setdefault(key, [[0,0],[255,255]])
    def rect_curve(self): return self.rect().adjusted(28,12,-12,-26)
    def pos(self,p):
        r=self.rect_curve(); return QPointF(r.left()+p[0]*r.width()/255, r.bottom()-p[1]*r.height()/255)
    def value(self,p):
        r=self.rect_curve(); return [round(max(0,min(255,(p.x()-r.left())*255/r.width()))),round(max(0,min(255,(r.bottom()-p.y())*255/r.height())))]
    def paintEvent(self,event):
        p=QPainter(self); p.fillRect(self.rect(),QColor(COLORS["curve_surface"])); r=self.rect_curve(); p.setPen(QPen(QColor(COLORS["curve_grid"])))
        for i in range(5):
            x=r.left()+i*r.width()/4; y=r.top()+i*r.height()/4; p.drawLine(int(x),r.top(),int(x),r.bottom()); p.drawLine(r.left(),int(y),r.right(),int(y))
        p.setPen(QPen(QColor(COLORS["curve_reference"]),1,Qt.PenStyle.DashLine)); p.drawLine(r.bottomLeft(),r.topRight()); points=sorted(self.curves[self.channel]); p.setPen(QPen(QColor(self.colors[self.channel]),2))
        for a,b in zip(points,points[1:]): p.drawLine(self.pos(a),self.pos(b))
        p.setBrush(QColor(self.colors[self.channel])); p.setPen(QPen(QColor(COLORS["curve_point_border"])))
        for point in points: p.drawEllipse(self.pos(point),5,5)
        p.setPen(QColor(COLORS["curve_text"])); p.drawText(3,r.top()+5,"255"); p.drawText(10,r.bottom(),"0"); p.drawText(r.left(),self.height()-5,"0"); p.drawText(r.right()-20,self.height()-5,"255")
    def mousePressEvent(self,e):
        if e.button()!=Qt.MouseButton.LeftButton:return
        points=self.curves[self.channel]; self.drag=next((i for i,v in enumerate(points) if (self.pos(v)-e.position()).manhattanLength()<12),None)
        if self.drag is None and self.rect_curve().contains(e.position().toPoint()):
            v=self.value(e.position()); points.append(v); points.sort(); self.drag=points.index(v); self.changed.emit()
        self.update()
    def mouseMoveEvent(self,e):
        if self.drag is None:return
        points=self.curves[self.channel]; v=self.value(e.position())
        if self.drag==0:v[0]=0
        elif self.drag==len(points)-1:v[0]=255
        else:v[0]=max(points[self.drag-1][0]+1,min(points[self.drag+1][0]-1,v[0]))
        points[self.drag]=v; self.changed.emit(); self.update()
    def mouseReleaseEvent(self,e): self.drag=None

class AdjustmentLayerDialog(QDialog):
    def __init__(self, adjustment:dict, parent=None):
        super().__init__(parent); self.spec=dict(adjustment or {}); self.kind=str(self.spec.get("kind","curves")); self.setWindowTitle({"levels":"Niveaux","hue_saturation":"Teinte / Saturation","exposure":"Exposition","brightness_contrast":"Luminosité / Contraste","vibrance":"Vibrance","color_balance":"Balance des couleurs","invert":"Inverser","threshold":"Seuil","posterize":"Postérisation","parametric_curves":"Courbes paramétriques","selective_color":"Couleur sélective","luminosity_mask":"Masque de luminosité"}.get(self.kind,"Courbes RVB")); self.setMinimumWidth(360)
        root=QVBoxLayout(self); form=QFormLayout(); root.addLayout(form); self.controls={}; self.mask_controls={}
        if self.kind=="curves":
            raw=dict(self.spec.get("curves",{})); curves={"rgb":raw.get("points",[[0,0],[255,255]])}; curves.update({{"r":"red","g":"green","b":"blue"}.get(k,k):v for k,v in dict(raw.get("channels",{})).items()})
            self.channel=QComboBox(self); self.channel.addItems(["RVB","Rouge","Vert","Bleu"]); form.addRow("Canal",self.channel); self.editor=CurveEditor(curves,self); root.addWidget(self.editor); self.channel.currentIndexChanged.connect(lambda i:self.set_channel(("rgb","red","green","blue")[i]))
        elif self.kind=="levels":
            v=dict(self.spec.get("levels",{})); self.integer(form,"Noir","black",v.get("black",0),0,254); self.integer(form,"Blanc","white",v.get("white",255),1,255); self.decimal(form,"Gamma","gamma",v.get("gamma",1),.01,10,2); self.integer(form,"Sortie noire","output_black",v.get("output_black",0),0,255); self.integer(form,"Sortie blanche","output_white",v.get("output_white",255),0,255)
        elif self.kind=="hue_saturation":
            v=dict(self.spec.get("hue_saturation",{})); self.decimal(form,"Teinte","hue",v.get("hue",0),-180,180,1); self.decimal(form,"Saturation","saturation",v.get("saturation",0),-100,100,1); self.decimal(form,"Luminosité","lightness",v.get("lightness",0),-100,100,1)
        elif self.kind=="exposure":
            v=dict(self.spec.get("exposure",{})); self.decimal(form,"Exposition","exposure",v.get("exposure",0),-5,5,.01); self.decimal(form,"Décalage","offset",v.get("offset",0),-1,1,.001); self.decimal(form,"Gamma","gamma",v.get("gamma",1),.01,5,.01)
        elif self.kind=="brightness_contrast":
            v=dict(self.spec.get("brightness_contrast",{})); self.decimal(form,"Luminosité","brightness",v.get("brightness",0),-100,100,1); self.decimal(form,"Contraste","contrast",v.get("contrast",0),-100,100,1)
        elif self.kind=="vibrance":
            v=dict(self.spec.get("vibrance",{})); self.decimal(form,"Vibrance","vibrance",v.get("vibrance",0),-100,100,1); self.decimal(form,"Saturation","saturation",v.get("saturation",0),-100,100,1)
        elif self.kind=="color_balance":
            v=dict(self.spec.get("color_balance",{}))
            for zone, label in (("shadows","Ombres"),("midtones","Tons moyens"),("highlights","Hautes lumières")):
                values=list(v.get(zone,(0,0,0)))
                for index, channel in enumerate(("R","V","B")):
                    self.decimal(form,f"{label} {channel}",f"{zone}_{index}",values[index] if index < len(values) else 0,-100,100,1)
        elif self.kind=="threshold":
            self.integer(form,"Seuil","threshold",self.spec.get("threshold",128),0,255)
        elif self.kind=="posterize":
            self.integer(form,"Niveaux","posterize",self.spec.get("posterize",4),2,32)
        elif self.kind=="parametric_curves":
            v=dict(self.spec.get("parametric_curves",{}))
            for key, label in (("black","Noirs"),("shadows","Ombres"),("midtones","Tons moyens"),("highlights","Hautes lumières"),("white","Blancs")):
                self.decimal(form,label,key,v.get(key,0),-100,100,1)
        elif self.kind=="luminosity_mask":
            v=dict(self.spec.get("luminosity_mask",{})); self.mode=QComboBox(self); self.mode.addItems(["lights","midtones","shadows"]); self.mode.setCurrentText(v.get("mode","lights")); form.addRow("Plage",self.mode); self.decimal(form,"Intensité","amount",v.get("amount",1),0,1,.01); self.decimal(form,"Adoucissement","feather",v.get("feather",.15),.01,1,.01)
        elif self.kind=="selective_color":
            self.selective_channels={}; colors=("reds","yellows","greens","cyans","blues","magentas","whites","neutrals","blacks"); values=dict(self.spec.get("selective_color",{}).get("channels",{}))
            for channel in colors:
                row=[]; raw=list(values.get(channel,(0,0,0,0)))
                for index, label in enumerate(("C","M","J","N")):
                    key=f"{channel}_{index}"; self.decimal(form,f"{channel} {label}",key,raw[index] if index < len(raw) else 0,-100,100,1); row.append(key)
                self.selective_channels[channel]=row
        if self.kind != "luminosity_mask":
            mask=dict(self.spec.get("luminosity_mask",{})); self.mask_mode=QComboBox(self); self.mask_mode.addItems(["none","lights","midtones","shadows"]); self.mask_mode.setCurrentText(mask.get("mode","none")); form.addRow("Masque de luminosité",self.mask_mode); self.decimal_mask(form,"Intensité", "amount", mask.get("amount",1), 0, 1, .01); self.decimal_mask(form,"Adoucissement", "feather", mask.get("feather",.15), .01, 1, .01)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)
    def set_channel(self,c):self.editor.channel=c;self.editor.update()
    def integer(self,f,l,k,v,a,b): c=QSpinBox(self);c.setRange(a,b);c.setValue(int(v));f.addRow(l,c);self.controls[k]=c
    def decimal(self,f,l,k,v,a,b,d): c=QDoubleSpinBox(self);c.setRange(a,b);c.setDecimals(d);c.setValue(float(v));f.addRow(l,c);self.controls[k]=c
    def decimal_mask(self,f,l,k,v,a,b,d): c=QDoubleSpinBox(self);c.setRange(a,b);c.setDecimals(d);c.setValue(float(v));f.addRow(l,c);self.mask_controls[k]=c
    def result_spec(self):
        r=dict(self.spec)
        if self.kind=="curves":r["curves"]={"points":self.editor.curves["rgb"],"channels":{k:self.editor.curves[k] for k in ("red","green","blue")}}
        elif self.kind=="levels":r["levels"]={k:c.value() for k,c in self.controls.items()}
        elif self.kind=="hue_saturation":r["hue_saturation"]={k:c.value() for k,c in self.controls.items()}
        elif self.kind=="exposure":r["exposure"]={k:c.value() for k,c in self.controls.items()}
        elif self.kind=="brightness_contrast":r["brightness_contrast"]={k:c.value() for k,c in self.controls.items()}
        elif self.kind=="vibrance":r["vibrance"]={k:c.value() for k,c in self.controls.items()}
        elif self.kind=="color_balance":r["color_balance"]={zone:[self.controls[f"{zone}_{i}"].value() for i in range(3)] for zone in ("shadows","midtones","highlights")}
        elif self.kind=="threshold":r["threshold"]=self.controls["threshold"].value()
        elif self.kind=="posterize":r["posterize"]=self.controls["posterize"].value()
        elif self.kind=="parametric_curves":r["parametric_curves"]={k:self.controls[k].value() for k in ("black","shadows","midtones","highlights","white")}
        elif self.kind=="luminosity_mask":r["luminosity_mask"]={"mode":self.mode.currentText(),"amount":self.controls["amount"].value(),"feather":self.controls["feather"].value(),"invert":False}
        elif self.kind=="selective_color":r["selective_color"]={"channels":{channel:[self.controls[key].value() for key in keys] for channel,keys in self.selective_channels.items()}}
        if self.kind != "luminosity_mask" and hasattr(self, "mask_mode"):
            if self.mask_mode.currentText() == "none":
                r.pop("luminosity_mask", None)
            else:
                r["luminosity_mask"]={"mode":self.mask_mode.currentText(),"amount":self.mask_controls["amount"].value(),"feather":self.mask_controls["feather"].value(),"invert":False}
        return r
