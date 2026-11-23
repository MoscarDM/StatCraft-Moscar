"""Interactive output scaling; source widget/export coordinates stay at 100%."""
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QWidget


class OutputZoomView(QGraphicsView):
    def __init__(self, widget, parent=None):
        super().__init__(parent)
        self.content=widget;self.percent=100;self.fit_mode=False
        scene=QGraphicsScene(self);self.setScene(scene);self.proxy=scene.addWidget(widget)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setStyleSheet('QGraphicsView { border: none; background: #e6e6e6; }')
        self._resizing=False
        self.verticalScrollBar().rangeChanged.connect(self._on_vbar_range_changed)
        self.resize_content()

    def _on_vbar_range_changed(self,_min,_max):
        try:
            if self.percent==100 and not self.fit_mode:
                self.resize_content()
        except RuntimeError:
            return

    def _safe_resize_content(self):
        try:
            if self.percent==100 and not self.fit_mode:
                self.resize_content()
        except RuntimeError:
            return

    def resize_content(self):
        try:
            if getattr(self,'_resizing',False):return
            self._resizing=True
            try:
                vp=self.viewport().size()
                avail_w=(vp.width()-4) if vp.width()>6 else (self.width()-4)
                avail_h=(vp.height()-4) if vp.height()>6 else (self.height()-4)
                hint=self.content.minimumSizeHint()
                min_w=max(self.content.minimumWidth(),hint.width())
                min_h=max(self.content.minimumHeight(),hint.height())
                vbar=self.verticalScrollBar()
                if (
                    self.verticalScrollBarPolicy()!=Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                    and not vbar.isVisible()
                    and min_h>avail_h
                ):
                    vbar_w=max(12,vbar.sizeHint().width())
                    avail_w=max(1,avail_w-vbar_w)
                width=max(320,avail_w,min_w)
                if self.content.hasHeightForWidth():
                    hfw=self.content.heightForWidth(width)
                    if hfw>0:
                        min_h=max(min_h,hfw)
                height=max(180,avail_h,min_h)
                self.proxy.resize(width,height)
                self.scene().setSceneRect(self.proxy.boundingRect())
                if self.fit_mode:self.fit_window()
            finally:
                self._resizing=False
        except RuntimeError:
            return

    def showEvent(self,event):
        super().showEvent(event)
        QTimer.singleShot(0,self._safe_resize_content)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'proxy'):
            if self.fit_mode:
                self.fit_window()
            elif self.percent==100:
                self.resize_content()

    def set_zoom(self,percent):
        self.fit_mode=False;self.percent=max(10,min(500,int(percent)))
        self.resetTransform();self.scale(self.percent/100,self.percent/100)

    def fit_window(self):
        self.fit_mode=True
        self.fitInView(self.proxy.boundingRect(),Qt.AspectRatioMode.KeepAspectRatio)
        self.percent=max(10,min(500,round(self.transform().m11()*100)))

    def wheelEvent(self, event):
        if hasattr(self, 'content') and self.content is not None:
            target_chart = None
            if hasattr(self.content, '_has_3d_panel') and self.content._has_3d_panel():
                target_chart = self.content
            elif hasattr(self.content, '_interactive_3d') and self.content._interactive_3d:
                target_chart = self.content
            else:
                for child in self.content.findChildren(QWidget):
                    if (hasattr(child, '_has_3d_panel') and child._has_3d_panel()) or (hasattr(child, '_interactive_3d') and child._interactive_3d):
                        target_chart = child
                        break
            if target_chart is None and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                scene_pt = self.mapToScene(event.position().toPoint())
                for child in ([self.content] + list(self.content.findChildren(QWidget))):
                    if hasattr(child, '_has_2d_zoomable_panel') and child._has_2d_zoomable_panel():
                        local_pt = QPointF(child.mapFrom(self.content, scene_pt.toPoint()))
                        if hasattr(child, '_zoom2d_panel_at') and child._zoom2d_panel_at(local_pt) is not None:
                            steps = event.angleDelta().y() / 120.0
                            if steps and child._apply_2d_wheel_zoom(local_pt, steps):
                                event.accept()
                                return
                            break
            if target_chart is not None:
                target_chart.wheelEvent(event)
                if event.isAccepted():
                    return
        super().wheelEvent(event)

