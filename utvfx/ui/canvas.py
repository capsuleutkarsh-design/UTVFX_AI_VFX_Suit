from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QPixmap

class InteractiveVideoCanvas(QWidget):
    interaction_requested = Signal(int, list) # frame_idx, [(nx, ny, is_positive), ...]
    keyframes_changed = Signal(list)
    zoom_changed = Signal()
    pixel_probed = Signal(int, int, int, int, int) # x, y, r, g, b
    
    def __init__(self, placeholder_text="NO MEDIA LOADED", parent=None):
        super().__init__(parent)
        self.placeholder_text = placeholder_text
        self.setMouseTracking(True)
        
        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        
        self.is_interactive = False
        self.current_frame = 0
        self.mask_layers = []
        self.active_layer_id = None
        self.mask_overlays = {}
        self.current_mask_overlay = None
        self.tracking_points = {}
        
        self.last_mouse_pos = None
        self.bg_mode = "black"
        
        # A/B Wipe Properties
        self.wipe_enabled = False
        self.last_b_image = None
        self.wipe_pos = 0.5
        self.is_dragging_wipe = False

    def setText(self, text):
        self.placeholder_text = text
        self.update()

    def text(self):
        return self.placeholder_text

    def clear(self):
        self.last_raw_image = None
        self.placeholder_text = ""
        self.update()

    def set_current_frame(self, frame_idx):
        if self.current_frame != frame_idx:
            # Restore the cached mask for this frame and active layer, if it exists
            self.current_mask_overlay = self.mask_overlays.get((self.active_layer_id, frame_idx), None)
            
            # Request mask generation if there are points for the active layer
            active_layer = next((l for l in self.mask_layers if l["id"] == self.active_layer_id), None)
            if self.current_mask_overlay is None and active_layer and frame_idx in active_layer.get("keyframes", {}):
                self.interaction_requested.emit(frame_idx, active_layer["keyframes"][frame_idx])
                
        self.current_frame = frame_idx
        self.update()

    def enable_interaction(self, enable):
        self.is_interactive = enable
        if not enable:
            self.current_mask_overlay = None
        self.update()
        
    def set_mask_overlay(self, layer_id, frame_idx, qimage):
        self.mask_overlays[(layer_id, frame_idx)] = qimage
        if self.current_frame == frame_idx and self.active_layer_id == layer_id:
            self.current_mask_overlay = qimage
            self.update()

    def clear_current_frame_points(self):
        active_layer = next((l for l in self.mask_layers if l["id"] == self.active_layer_id), None)
        if active_layer and "keyframes" in active_layer and self.current_frame in active_layer["keyframes"]:
            del active_layer["keyframes"][self.current_frame]
            cache_key = (self.active_layer_id, self.current_frame)
            if cache_key in self.mask_overlays:
                del self.mask_overlays[cache_key]
            self.current_mask_overlay = None
            self.keyframes_changed.emit(list(active_layer["keyframes"].keys()))
            self.update()

    def wheelEvent(self, event):
        # Zoom in/out with mouse scroll
        if event.angleDelta().y() > 0:
            self.zoom_factor *= 1.1
        else:
            self.zoom_factor /= 1.1
            
        self.zoom_factor = max(0.1, min(self.zoom_factor, 10.0))
        
        if hasattr(self, 'zoom_changed'):
            self.zoom_changed.emit()
        self.update()

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is not None:
            delta = event.position() - self.last_mouse_pos
            self.pan_x += delta.x()
            self.pan_y += delta.y()
            self.last_mouse_pos = event.position()
            self.update()
            
        # Pixel Probe
        if hasattr(self, 'last_raw_image') and self.last_raw_image and not self.last_raw_image.isNull():
            img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
            lbl_w, lbl_h = self.width(), self.height()
            
            scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
            drawn_w = img_w * scale
            drawn_h = img_h * scale
            
            x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
            y_offset = (lbl_h - drawn_h) / 2 + self.pan_y
            
            click_x = event.position().x() - x_offset
            click_y = event.position().y() - y_offset
            
            if 0 <= click_x <= drawn_w and 0 <= click_y <= drawn_h:
                px = int((click_x / drawn_w) * img_w)
                py = int((click_y / drawn_h) * img_h)
                
                # Safely probe pixel
                if 0 <= px < img_w and 0 <= py < img_h:
                    color = QColor(self.last_raw_image.pixel(px, py))
                    self.pixel_probed.emit(px, py, color.red(), color.green(), color.blue())
            
            if self.wipe_enabled and self.is_dragging_wipe:
                self.wipe_pos = max(0.0, min(1.0, click_x / drawn_w))
                self.update()
                
            if getattr(self, 'is_drawing_box', False):
                self.drag_current_pos = (click_x / drawn_w, click_y / drawn_h)
                self.update()
                    
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self.last_mouse_pos = event.position()
            
        elif event.button() == Qt.LeftButton:
            if self.wipe_enabled and hasattr(self, 'last_raw_image') and self.last_raw_image:
                img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
                lbl_w, lbl_h = self.width(), self.height()
                scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
                drawn_w = img_w * scale
                x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
                
                click_x = event.position().x() - x_offset
                wipe_px = drawn_w * self.wipe_pos
                
                if abs(click_x - wipe_px) < 15: # 15px hit radius
                    self.is_dragging_wipe = True
                    return

            if self.is_interactive and hasattr(self, 'last_raw_image') and self.last_raw_image:
                img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
                lbl_w, lbl_h = self.width(), self.height()
                
                scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
                drawn_w = img_w * scale
                drawn_h = img_h * scale
                
                x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
                y_offset = (lbl_h - drawn_h) / 2 + self.pan_y
                
                click_x = event.position().x() - x_offset
                click_y = event.position().y() - y_offset
                
                if 0 <= click_x <= drawn_w and 0 <= click_y <= drawn_h:
                    norm_x = click_x / drawn_w
                    norm_y = click_y / drawn_h
                    
                    tool_mode = "Point"
                    p = self.parent()
                    while p:
                        if hasattr(p, "current_node") and p.current_node:
                            tool_mode = p.current_node.params.get("tool_mode", "Point")
                            break
                        p = p.parent()
                        
                    if tool_mode == "Box":
                        self.drag_start_pos = (norm_x, norm_y)
                        self.drag_current_pos = (norm_x, norm_y)
                        self.is_drawing_box = True
                        self.update()
                        return
                    
                    is_positive = (event.modifiers() != Qt.ShiftModifier)
                    
                    active_layer = next((l for l in self.mask_layers if l["id"] == self.active_layer_id), None)
                    if active_layer:
                        if "keyframes" not in active_layer:
                            active_layer["keyframes"] = {}
                        if self.current_frame not in active_layer["keyframes"]:
                            active_layer["keyframes"][self.current_frame] = []
                            
                        active_layer["keyframes"][self.current_frame].append((norm_x, norm_y, is_positive))
                        self.keyframes_changed.emit(list(active_layer["keyframes"].keys()))
                        
                        # Emit interaction request for live preview
                        self.interaction_requested.emit(self.current_frame, active_layer["keyframes"][self.current_frame])
                        self.update()
            
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, 'is_drawing_box', False):
            self.is_drawing_box = False
            
            x1 = min(self.drag_start_pos[0], self.drag_current_pos[0])
            y1 = min(self.drag_start_pos[1], self.drag_current_pos[1])
            x2 = max(self.drag_start_pos[0], self.drag_current_pos[0])
            y2 = max(self.drag_start_pos[1], self.drag_current_pos[1])
            
            if x2 - x1 > 0.01 and y2 - y1 > 0.01:
                active_layer = next((l for l in self.mask_layers if l["id"] == self.active_layer_id), None)
                if active_layer:
                    if "keyframes" not in active_layer:
                        active_layer["keyframes"] = {}
                    if self.current_frame not in active_layer["keyframes"]:
                        active_layer["keyframes"][self.current_frame] = []
                        
                    active_layer["keyframes"][self.current_frame].append((x1, y1, x2, y2, "box"))
                    self.keyframes_changed.emit(list(active_layer["keyframes"].keys()))
                    self.interaction_requested.emit(self.current_frame, active_layer["keyframes"][self.current_frame])
            self.update()
            return
            
        self.is_dragging_wipe = False
        if event.button() in (Qt.MiddleButton, Qt.RightButton):
            self.last_mouse_pos = None

    def reset_zoom(self):
        self.zoom_factor = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()

    def mouseDoubleClickEvent(self, event):
        self.reset_zoom()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        if not hasattr(self, 'last_raw_image') or self.last_raw_image is None or self.last_raw_image.isNull():
            painter.setPen(QColor("#71717a"))
            painter.drawText(self.rect(), Qt.AlignCenter, self.placeholder_text)
            return
            
        img_w, img_h = self.last_raw_image.width(), self.last_raw_image.height()
        lbl_w, lbl_h = self.width(), self.height()
        
        scale = min(lbl_w / img_w, lbl_h / img_h) * self.zoom_factor
        drawn_w = img_w * scale
        drawn_h = img_h * scale
        
        x_offset = (lbl_w - drawn_w) / 2 + self.pan_x
        y_offset = (lbl_h - drawn_h) / 2 + self.pan_y
        
        drawn_rect = QRectF(x_offset, y_offset, drawn_w, drawn_h)
        
        # Draw Background Mode
        if self.bg_mode == "checkerboard":
            tile_size = 16
            tile_pm = QPixmap(tile_size * 2, tile_size * 2)
            tile_pm.fill(QColor("#a1a1aa"))
            tp = QPainter(tile_pm)
            tp.fillRect(0, 0, tile_size, tile_size, QColor("#e4e4e7"))
            tp.fillRect(tile_size, tile_size, tile_size, tile_size, QColor("#e4e4e7"))
            tp.end()
            painter.fillRect(drawn_rect, QBrush(tile_pm))
        elif self.bg_mode == "white":
            painter.fillRect(drawn_rect, Qt.white)
        else:
            painter.fillRect(drawn_rect, Qt.black)
            
        if self.wipe_enabled and self.last_b_image and not self.last_b_image.isNull():
            wipe_x = drawn_w * self.wipe_pos
            
            # Draw A (Left)
            rect_a_src = QRectF(0, 0, img_w * self.wipe_pos, img_h)
            rect_a_dst = QRectF(x_offset, y_offset, wipe_x, drawn_h)
            painter.drawImage(rect_a_dst, self.last_raw_image, rect_a_src)
            
            # Draw B (Right)
            rect_b_src = QRectF(img_w * self.wipe_pos, 0, img_w * (1 - self.wipe_pos), img_h)
            rect_b_dst = QRectF(x_offset + wipe_x, y_offset, drawn_w - wipe_x, drawn_h)
            painter.drawImage(rect_b_dst, self.last_b_image, rect_b_src)
            
            # Wipe Line
            painter.setPen(QPen(Qt.white, 3))
            painter.drawLine(x_offset + wipe_x, y_offset, x_offset + wipe_x, y_offset + drawn_h)
            # Draw small handle
            painter.setBrush(QBrush(Qt.white))
            painter.drawEllipse(QPointF(x_offset + wipe_x, y_offset + drawn_h / 2), 6, 6)
        else:
            painter.drawImage(drawn_rect, self.last_raw_image)
        
        if self.current_mask_overlay is not None and not self.current_mask_overlay.isNull():
            painter.setOpacity(0.55)
            painter.drawImage(drawn_rect, self.current_mask_overlay)
            painter.setOpacity(1.0)
        
        if self.is_interactive:
            for layer in self.mask_layers:
                is_active = (layer["id"] == self.active_layer_id)
                
                # (Points from inactive layers will be drawn dimmed/smaller below)
                points = layer.get("keyframes", {}).get(self.current_frame, [])
                layer_color = QColor(layer.get("color", "#ffffff"))
                
                for pt in points:
                    if len(pt) == 5:
                        x1, y1, x2, y2, prompt_type = pt
                        px1 = x_offset + (x1 * drawn_w)
                        py1 = y_offset + (y1 * drawn_h)
                        px2 = x_offset + (x2 * drawn_w)
                        py2 = y_offset + (y2 * drawn_h)
                        
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        if is_active:
                            painter.setPen(QPen(layer_color, 3, Qt.PenStyle.DashLine))
                        else:
                            painter.setPen(QPen(layer_color, 1, Qt.PenStyle.DashLine))
                        
                        painter.drawRect(QRectF(QPointF(px1, py1), QPointF(px2, py2)))
                    else:
                        nx, ny, is_pos = pt
                        px = x_offset + (nx * drawn_w)
                        py = y_offset + (ny * drawn_h)
                        
                        # Fill color: Green for positive, Red for negative
                        fill_color = QColor(34, 197, 94) if is_pos else QColor(239, 68, 68)
                        painter.setBrush(QBrush(fill_color))
                        
                        # Pen (outline): Layer color if active, otherwise dimmed
                        if is_active:
                            painter.setPen(QPen(layer_color, 3))
                            painter.drawEllipse(QPointF(px, py), 7, 7)
                        else:
                            painter.setPen(QPen(layer_color, 1))
                            painter.drawEllipse(QPointF(px, py), 5, 5)
                
        # Draw camera tracking points
        if getattr(self, "show_tracking", False) and self.current_frame in self.tracking_points:
            t_points = self.tracking_points[self.current_frame]
            painter.setPen(Qt.NoPen)
            for tx, ty, has_3d in t_points:
                nx = tx / img_w
                ny = ty / img_h
                px = x_offset + (nx * drawn_w)
                py = y_offset + (ny * drawn_h)
                
                # Orange if matched to 3D point, gray if 2D only
                color = QColor(249, 115, 22) if has_3d else QColor(156, 163, 175, 100)
                painter.setBrush(QBrush(color))
                painter.drawRect(px - 1.5, py - 1.5, 3, 3)
                
        if getattr(self, 'is_drawing_box', False) and hasattr(self, 'drag_start_pos') and hasattr(self, 'drag_current_pos'):
            x1 = self.drag_start_pos[0]
            y1 = self.drag_start_pos[1]
            x2 = self.drag_current_pos[0]
            y2 = self.drag_current_pos[1]
            
            px1 = x_offset + (min(x1, x2) * drawn_w)
            py1 = y_offset + (min(y1, y2) * drawn_h)
            px2 = x_offset + (max(x1, x2) * drawn_w)
            py2 = y_offset + (max(y1, y2) * drawn_h)
            
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(249, 115, 22), 2, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(QPointF(px1, py1), QPointF(px2, py2)))
            
        painter.end()
