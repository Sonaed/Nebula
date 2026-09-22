from PySide6.QtGui import QImage
from PySide6.QtCore import QPoint

from TOOLS.brush import Brush
from TOOLS.move_tool import MoveTool
from TOOLS.fill_tool import FillTool
from TOOLS.gradient_tool import GradientTool
from TOOLS.shape_tools import ShapeTools
from TOOLS.selection_tools import SelectionTools
from TOOLS.transform_tool import TransformTool
from TOOLS.crop_tool import CropTool


class ToolManager:

    def __init__(self, on_tool_changed=None) -> None:

        self.brush: Brush = Brush()

        self.move_tool: MoveTool = MoveTool()

        self.fill_tool: FillTool = FillTool()

        self.gradient_tool: GradientTool = GradientTool()

        self.shape_tools: ShapeTools = ShapeTools()
        self.selection_tools: SelectionTools = SelectionTools()
        self.transform_tool: TransformTool = TransformTool()
        self.crop_tool: CropTool = CropTool()

        self.current_tool: str = "brush"
        self.on_tool_changed = on_tool_changed

    def _select_tool(self, name: str, eraser: bool = False) -> None:
        self.current_tool = name
        self.brush.eraser = eraser
        self.move_tool.end()
        if self.on_tool_changed is not None:
            self.on_tool_changed(name)

    def set_cpp_library(self, library) -> None:
        self.fill_tool.cpp_library = library
        self.selection_tools.cpp_library = library

    # =========================================================
    # OUTILS
    # =========================================================

    def set_brush(
        self
    ) -> None:

        self._select_tool("brush")

    def set_eraser(
        self
    ) -> None:

        self._select_tool("eraser", True)

    def set_picker(self) -> None:
        self._select_tool("picker")

    def set_smudge(self) -> None:
        self._select_tool("smudge")

    def set_clone_stamp(self) -> None:
        self._select_tool("clone_stamp")

    def set_reference(self) -> None:
        self._select_tool("reference")

    def set_text(self) -> None:
        self._select_tool("text")

    def set_blur(self) -> None:
        self._select_tool("blur")

    def set_sharpen(self) -> None:
        self._select_tool("sharpen")

    def set_bezier(self) -> None:
        self._select_tool("bezier")

    def set_fill(self) -> None:
        self._select_tool("fill")

    def set_gradient(self) -> None:
        self._select_tool("gradient")

    def set_line(self) -> None:
        self._select_tool("line")

    def set_rectangle(self) -> None:
        self._select_tool("rectangle")

    def set_ellipse(self) -> None:
        self._select_tool("ellipse")

    def set_rectangle_selection(self) -> None:
        self._select_tool("select_rectangle")

    def set_ellipse_selection(self) -> None:
        self._select_tool("select_ellipse")

    def set_lasso(self) -> None:
        self._select_tool("lasso")

    def set_magic_wand(self) -> None:
        self._select_tool("magic_wand")

    def set_crop(self) -> None:
        self._select_tool("crop")

    def set_move(
        self
    ) -> None:

        self._select_tool("move")

    def set_transform(
        self
    ) -> None:

        self._select_tool("transform")

    def set_hand(self) -> None:
        self._select_tool("hand")

    def set_zoom_view(self) -> None:
        self._select_tool("zoom_view")

    def set_rotate_view(self) -> None:
        self._select_tool("rotate_view")

    # =========================================================
    # DESSIN
    # =========================================================

    def draw(
        self,
        image: QImage,
        start_point: QPoint,
        end_point: QPoint
    ) -> None:

        self.brush.draw(
            image,
            start_point,
            end_point
        )

    def fill(self, image: QImage, position: QPoint, color) -> object:
        if self.current_tool != "fill":
            return None
        return self.fill_tool.fill(image, position, color)

    def gradient(self, image: QImage, start, end, color) -> object:
        if self.current_tool != "gradient":
            return None
        return self.gradient_tool.apply(image, start, end, color)

    def shape_path(self, start, end):
        return self.shape_tools.path(self.current_tool, start, end)

    # =========================================================
    # DÉPLACER
    # =========================================================

    def begin_move(
        self,
        position: QPoint
    ) -> None:

        if self.current_tool != "move":
            return

        self.move_tool.begin(
            position
        )

    def move(
        self,
        image: QImage,
        position: QPoint
    ) -> bool:

        if self.current_tool != "move":
            return False

        return self.move_tool.move(
            image,
            position
        )

    def end_move(
        self
    ) -> None:

        self.move_tool.end()
