# <<< START OF MODIFIED FILE grok36_mod.py >>>

import sys
import json
import ctypes
import platform
from ctypes import wintypes
from copy import deepcopy
import math
import traceback # For detailed error logging
import time # For double-press detection


# Try importing QtPrintSupport, handle gracefully if missing
_QT_PRINT_SUPPORT_AVAILABLE = False
try:
    from PySide6.QtPrintSupport import QPrinter, QPrintDialog
    _QT_PRINT_SUPPORT_AVAILABLE = True
    print("QtPrintSupport found.")
except ImportError:
    print("WARNING: QtPrintSupport module not found. Printing functionality will be disabled.")
    # Define dummy classes if module is missing to avoid NameError later
    class QPrinter: pass
    class QPrintDialog: pass


from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLabel, QColorDialog,
    QSlider, QRadioButton, QButtonGroup, QFileDialog, QDialog, QTextEdit,
    QFontComboBox, QSpinBox, QComboBox, QCheckBox, QHBoxLayout, QDockWidget,
    QFrame, QSizePolicy, QMessageBox, QTableWidget, QTableWidgetItem, # Added Table classes
    QHeaderView, QStyle # Added QStyle
)
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPolygonF, QGuiApplication, QFont, QTransform,
    QScreen, QCursor, QPixmap, QFontMetrics, QPalette, QKeyEvent, QTextDocument, # Added QTextDocument
    QMouseEvent, QShowEvent # Added QShowEvent
)

# Add QSettings, QRect explicitly if not already fully imported
from PySide6.QtCore import Qt, QPointF, QRectF, QSizeF, QTimer, Signal, Slot, QEvent, QRect, QSettings, QPoint, QAbstractNativeEventFilter

class GlobalHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == "windows_generic_MSG":
            try:
                msg = ctypes.wintypes.MSG.from_address(message.__int__())
                if msg.message == 0x0312:  # WM_HOTKEY
                    hotkey_id = msg.wParam
                    print(f"[FILTER] Hotkey pressed! ID: {hotkey_id}")
                    self.callback(hotkey_id)
            except Exception as e:
                print(f"Error in nativeEventFilter: {e}")
        return False, 0
        
# --- Definicje WinAPI ---
_IS_WINDOWS = platform.system() == "Windows"
if _IS_WINDOWS:
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        RGN_OR = 2
        CreateRectRgn = gdi32.CreateRectRgn
        CombineRgn = gdi32.CombineRgn
        DeleteObject = gdi32.DeleteObject
        SetWindowRgn = user32.SetWindowRgn
        # For global hotkeys
        RegisterHotKey = user32.RegisterHotKey
        UnregisterHotKey = user32.UnregisterHotKey
        MOD_NOREPEAT = 0x4000 # Prevent auto-repeat (might not be needed/used)
        # Define modifiers
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        MOD_SHIFT = 0x0004
        MOD_WIN = 0x0008
        print("WinAPI libraries loaded successfully")
    except OSError as e:
        print(f"Error loading WinAPI libraries: {e}. Regiony okna i globalne skróty klawiszowe mogą nie działać.")
        user32 = gdi32 = None
        CreateRectRgn = CombineRgn = DeleteObject = SetWindowRgn = lambda *args: None
        RegisterHotKey = UnregisterHotKey = lambda *args: None
        MOD_ALT = MOD_CONTROL = MOD_SHIFT = MOD_WIN = 0 # Dummy values
        _IS_WINDOWS = False
else:
    user32 = gdi32 = None
    CreateRectRgn = CombineRgn = DeleteObject = SetWindowRgn = lambda *args: None
    RegisterHotKey = UnregisterHotKey = lambda *args: None
    MOD_ALT = MOD_CONTROL = MOD_SHIFT = MOD_WIN = 0 # Dummy values
    print("Non-Windows system detected. Window region and global hotkey functionality unavailable.")

# Global Hotkey IDs
HOTKEY_ID_ALT_F1 = 1 # Toggle Drawing Mode
HOTKEY_ID_ALT_F2 = 2 # Enter EDIT Mode
HOTKEY_ID_ALT_F3 = 3 # Enter BOARD Mode

# --- Klasa Shape ---
class Shape:
    def __init__(self, shape_type, geometry, color, filled=True, alpha=255, line_thickness=2, line_style=Qt.SolidLine, rotation=0, text_properties=None, arrow_head_size=None):
        self.type = shape_type
        self.geometry = geometry # Can be QRectF or List[QPointF]
        self.color = QColor(color) if not isinstance(color, QColor) else color # Ensure QColor
        self.filled = filled
        self.alpha = alpha # Overall shape opacity
        self.line_thickness = max(1, line_thickness) # Ensure minimum thickness of 1
        self.line_style = line_style # Should be Qt.PenStyle enum
        self.rotation = rotation # In degrees
        # Text properties are deepcopied on assignment and retrieval to avoid shared references
        self.text_properties = deepcopy(text_properties) if shape_type == 'text' else None
        self.arrow_head_size = arrow_head_size if shape_type == 'arrow' else None

    def get_geometry_for_region(self):
        # print(f"Computing region for shape type: {self.type}") # Reduced logging
        if not _IS_WINDOWS:
            return None
        # Add buffer based on line thickness, ensure minimum buffer
        thickness_buffer = math.ceil(max(self.line_thickness, 1) / 2.0) + 2
        if self.type in ['rect', 'ellipse', 'text'] and isinstance(self.geometry, QRectF):
            if not self.geometry.isValid(): return None # Skip invalid rects
            if self.rotation != 0:
                center = self.geometry.center()
                transform = QTransform().translate(center.x(), center.y()).rotate(self.rotation).translate(-center.x(), -center.y())
                # Map the four corners and find bounding box
                poly = transform.mapToPolygon(self.geometry.toRect())
                bounding_rect = poly.boundingRect()
            else:
                bounding_rect = self.geometry.toRect()
            # Ensure minimum size for region calculation
            if bounding_rect.width() < 1: bounding_rect.setWidth(1)
            if bounding_rect.height() < 1: bounding_rect.setHeight(1)
            return bounding_rect.adjusted(-thickness_buffer, -thickness_buffer, thickness_buffer, thickness_buffer)

        elif self.type in ['triangle', 'polygon', 'brush', 'line', 'line_point', 'arrow'] and isinstance(self.geometry, list): # Added line_point
            valid_points = [p for p in self.geometry if isinstance(p, QPointF)]
            if not valid_points: return None # Need points to define geometry

            # Handle line/arrow special case (only 2 points needed)
            if self.type in ['line', 'arrow'] and len(valid_points) != 2: return None

            # Handle polygon/triangle minimum points
            if self.type in ['triangle', 'polygon'] and len(valid_points) < 3: return None

            # Handle brush/line_point minimum points
            if self.type in ['brush', 'line_point'] and len(valid_points) < 1: return None

            points_to_bound = valid_points
            # Apply rotation if needed
            if self.rotation != 0:
                # Calculate centroid for rotation
                if len(valid_points) > 0: # Avoid division by zero
                    center = QPointF(sum(p.x() for p in valid_points) / len(valid_points),
                                     sum(p.y() for p in valid_points) / len(valid_points))
                    transform = QTransform().translate(center.x(), center.y()).rotate(self.rotation).translate(-center.x(), -center.y())
                    points_to_bound = [transform.map(p) for p in valid_points]
                # else: cannot rotate if no valid points

            # Calculate bounding box of (potentially rotated) points
            if not points_to_bound: return None # Check again after rotation attempt
            xs = [p.x() for p in points_to_bound]
            ys = [p.y() for p in points_to_bound]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            bounding_rect = QRectF(min_x, min_y, max(1, max_x - min_x), max(1, max_y - min_y)).toRect() # Ensure min 1 size

            # Additional geometry for arrow head
            if self.type == 'arrow' and self.arrow_head_size and self.arrow_head_size > 0 and len(points_to_bound) == 2:
                 p1, p2 = points_to_bound # Use potentially rotated points
                 delta = p2 - p1
                 length = math.sqrt(delta.x()**2 + delta.y()**2)
                 if length > 1e-6:
                      angle_rad = math.atan2(delta.y(), delta.x())
                      arrow_size = self.arrow_head_size
                      a1_rad = angle_rad + math.radians(150)
                      head_p1 = p2 + QPointF(math.cos(a1_rad) * arrow_size, math.sin(a1_rad) * arrow_size)
                      a2_rad = angle_rad - math.radians(150)
                      head_p2 = p2 + QPointF(math.cos(a2_rad) * arrow_size, math.sin(a2_rad) * arrow_size)
                      # Include head points in bounding box calculation
                      head_xs = [head_p1.x(), head_p2.x()]
                      head_ys = [head_p1.y(), head_p2.y()]
                      min_x = min(min_x, min(head_xs))
                      max_x = max(max_x, max(head_xs))
                      min_y = min(min_y, min(head_ys))
                      max_y = max(max_y, max(head_ys))
                      bounding_rect = QRectF(min_x, min_y, max(1, max_x - min_x), max(1, max_y - min_y)).toRect()

            return bounding_rect.adjusted(-thickness_buffer, -thickness_buffer, thickness_buffer, thickness_buffer)

        return None # Unknown type or invalid geometry

    def contains(self, point):
        """Check if a QPointF 'point' is contained within the shape's geometry."""
        if not self.geometry: return False # Cannot contain if no geometry

        transformed_point = point
        center = QPointF()
        geo = self.geometry

        # Calculate center for rotation transform
        if isinstance(geo, QRectF) and geo.isValid():
            center = geo.center()
        elif isinstance(geo, list):
            valid_points = [p for p in geo if isinstance(p, QPointF)]
            if valid_points:
                center = QPointF(sum(p.x() for p in valid_points) / len(valid_points),
                                 sum(p.y() for p in valid_points) / len(valid_points))

        # Apply inverse rotation to the test point
        if self.rotation != 0 and not center.isNull():
            try:
                 transform = QTransform().translate(center.x(), center.y()).rotate(-self.rotation).translate(-center.x(), -center.y())
                 transformed_point = transform.map(point)
            except Exception as e:
                 print(f"Error applying inverse transform: {e}")
                 return False # Cannot determine containment if transform fails


        # --- Perform containment check based on shape type ---
        if self.type in ['rect', 'text'] and isinstance(geo, QRectF):
            return geo.contains(transformed_point)

        elif self.type == 'ellipse' and isinstance(geo, QRectF):
            if not geo.isValid() or geo.width() <= 0 or geo.height() <= 0: return False
            center_ellipse = geo.center()
            rx = geo.width() / 2.0
            ry = geo.height() / 2.0
             # Avoid division by zero if radius is extremely small
            if abs(rx) < 1e-6 or abs(ry) < 1e-6: return False
            # Normalized distance check
            dx = (transformed_point.x() - center_ellipse.x()) / rx
            dy = (transformed_point.y() - center_ellipse.y()) / ry
            return (dx * dx + dy * dy) <= 1.0

        elif self.type in ['triangle', 'polygon'] and isinstance(geo, list):
            valid_geo = [p for p in geo if isinstance(p, QPointF)]
            if len(valid_geo) < 3: return False
            # Ray casting algorithm (Point in Polygon)
            inside = False
            j = len(valid_geo) - 1
            for i in range(len(valid_geo)):
                xi, yi = valid_geo[i].x(), valid_geo[i].y()
                xj, yj = valid_geo[j].x(), valid_geo[j].y()
                # Check if edge crosses horizontal ray from point
                intersect = ((yi > transformed_point.y()) != (yj > transformed_point.y())) and \
                            (transformed_point.x() < (xj - xi) * (transformed_point.y() - yi) / (yj - yi + 1e-10) + xi) # Add epsilon for vertical lines
                if intersect:
                    inside = not inside
                j = i
            return inside

        elif self.type in ['brush', 'line_point'] and isinstance(geo, list): # Added line_point
            valid_geo = [p for p in geo if isinstance(p, QPointF)]
            if not valid_geo: return False
            # Check distance to line segments or single point
            # Increase tolerance slightly for easier clicking
            tolerance = max(self.line_thickness / 2.0, 1.0) + 3.0
            if len(valid_geo) == 1:
                # Check distance to the single point
                dist_sq = (transformed_point.x() - valid_geo[0].x())**2 + (transformed_point.y() - valid_geo[0].y())**2
                return dist_sq <= tolerance**2
            else:
                # Check distance to each segment
                for i in range(len(valid_geo) - 1):
                    p1 = valid_geo[i]
                    p2 = valid_geo[i+1]
                    dist_sq = self._point_segment_distance_sq(transformed_point, p1, p2)
                    if dist_sq <= tolerance**2:
                        return True
                return False

        elif self.type in ['line', 'arrow'] and isinstance(geo, list) and len(geo) == 2:
            p1, p2 = geo
            if not isinstance(p1, QPointF) or not isinstance(p2, QPointF): return False
            dist_sq = self._point_segment_distance_sq(transformed_point, p1, p2)
             # Increase tolerance slightly for easier clicking
            tolerance = max(self.line_thickness / 2.0, 1.0) + 5.0
            return dist_sq <= tolerance**2

        return False # Default: point not contained

    def _point_segment_distance_sq(self, p, a, b):
        """Calculate the squared distance from point p to line segment ab."""
        ab = b - a
        ap = p - a
        ab_len_sq = QPointF.dotProduct(ab, ab) # Use QPointF's dotProduct

        if ab_len_sq < 1e-10: # Segment is essentially a point
            return QPointF.dotProduct(ap, ap) # Distance from p to a

        # Project ap onto ab
        t = QPointF.dotProduct(ap, ab) / ab_len_sq

        # Clamp t to the range [0, 1] to stay on the segment
        t = max(0, min(1, t))

        # Find the closest point on the segment
        closest_point = a + t * ab
        d = p - closest_point
        return QPointF.dotProduct(d, d) # Squared distance

    def to_dict(self):
        """Serialize Shape object to a dictionary."""
        geo_data = None
        if isinstance(self.geometry, QRectF):
            if self.geometry.isValid():
                 geo_data = (self.geometry.x(), self.geometry.y(), self.geometry.width(), self.geometry.height())
            else:
                 pass # Keep geo_data as None
        elif isinstance(self.geometry, list):
            valid_points = [p for p in self.geometry if isinstance(p, QPointF)]
            if len(valid_points) == len(self.geometry): # Ensure all were valid QPointF
                geo_data = [(p.x(), p.y()) for p in valid_points]
            else:
                 if not self.geometry:
                      geo_data = []
                 else:
                      print(f"Warning: Geometry list contains non-QPointF elements for shape {self.type}. Saving geometry as None.")
                      geo_data = None # Set to None if invalid points found
        # else: geo_data remains None

        # --- FIX: Get integer value of PenStyle enum ---
        line_style_int = Qt.SolidLine.value # Default
        if self.line_style is not None:
            try:
                # Attempt to get the integer value
                line_style_int = self.line_style.value
            except AttributeError:
                print(f"Warning: Could not get .value from line_style '{self.line_style}'. Assuming it's already an int.")
                # Fallback: Assume it might already be an integer (less likely with current code)
                if isinstance(self.line_style, int):
                    line_style_int = self.line_style
                else:
                    print(f"Error: Unknown type for self.line_style: {type(self.line_style)}. Defaulting to SolidLine value.")
                    line_style_int = Qt.SolidLine.value

        # Ensure color is valid before getting name
        color_name = self.color.name(QColor.HexArgb) if self.color and self.color.isValid() else QColor(Qt.red).name(QColor.HexArgb)

        data = {
            'type': self.type,
            'geometry': geo_data,
            'color': color_name, # Use HexArgb
            'filled': self.filled,
            'alpha': self.alpha,
            'line_thickness': self.line_thickness,
            'line_style': line_style_int, # Use the integer value
            'rotation': self.rotation,
             # Deepcopy text properties on serialization as well
            'text_properties': deepcopy(self.text_properties) if self.type == 'text' else None,
            'arrow_head_size': self.arrow_head_size
        }
        return data


    @staticmethod
    def from_dict(data):
        """Deserialize dictionary into a Shape object."""
        st = data.get('type')
        gd = data.get('geometry')
        # --- Color Handling ---
        cs = data.get('color')
        default_color = QColor(255, 0, 0, 255) # Default opaque red
        c = default_color
        if cs:
             temp_c = QColor(cs)
             if temp_c.isValid():
                  c = temp_c
             else:
                  print(f"Warning: Invalid color string '{cs}' in data. Using default red.")
        else:
             print("Warning: Missing color in data. Using default red.")

        # --- Other properties ---
        fd = data.get('filled', True)
        # Use alpha from color string if available, otherwise from 'alpha' field, default to 255
        al = c.alpha() if c.isValid() else data.get('alpha', 255)
        lt = data.get('line_thickness', 1)
        # --- FIX: Load Line Style from integer ---
        ls_int = data.get('line_style', Qt.SolidLine.value) # Default to SolidLine's value
        ls = Qt.SolidLine # Default enum
        try:
            # Convert integer value back to Qt.PenStyle enum
            ls = Qt.PenStyle(ls_int)
        except ValueError:
            print(f"Warning: Invalid line style int: {ls_int}. Using SolidLine.")
            ls = Qt.SolidLine

        rt = data.get('rotation', 0)
        # Deepcopy text properties on deserialization
        tp = deepcopy(data.get('text_properties', None)) if st == 'text' else None
        ahs = data.get('arrow_head_size', 10 if st == 'arrow' else None)

        if not st:
            print(f"Warning: Missing 'type' in shape data: {data}")
            return None

        # --- Geometry Reconstruction ---
        g = None
        if gd is not None:
            if st in ['rect', 'ellipse', 'text'] and isinstance(gd, (list, tuple)) and len(gd) == 4:
                try:
                    g = QRectF(float(gd[0]), float(gd[1]), float(gd[2]), float(gd[3]))
                    if not g.isValid():
                         print(f"Warning: Reconstructed QRectF is invalid: {gd}. Setting geometry to None.")
                         g = None
                except (ValueError, TypeError) as e:
                    print(f"Warning: Error converting QRectF geometry: {e}, data: {gd}")
                    g = None # Set to None on error
            elif st in ['triangle', 'polygon', 'line', 'line_point', 'arrow', 'brush'] and isinstance(gd, list): # Added line_point
                try:
                    points = [QPointF(float(p[0]), float(p[1])) for p in gd if isinstance(p, (list, tuple)) and len(p) == 2]
                    if len(points) == len(gd): # Check all points converted correctly
                        g = points
                    elif not gd: # Allow empty geometry list
                         g = []
                    else:
                         print(f"Warning: Invalid point format or mix in List[QPointF] geometry: {gd}. Setting geometry to None.")
                         g = None # Set to None if invalid points found
                except (ValueError, TypeError, IndexError) as e:
                    print(f"Warning: Error converting List[QPointF] geometry: {e}, data: {gd}")
                    g = None # Set to None on error
            else:
                print(f"Warning: Unsupported geometry type or data format for shape type '{st}': data={gd}")
                # Allow shape creation without geometry if data is None (gd is None)
        # Allow creation if geometry is None (e.g., text before dialog, or load error)
        try:
            # Use the main 'alpha' field as the primary source of truth for shape alpha
            shape_alpha = data.get('alpha', 255)
            # Pass the *reconstructed* color 'c' and the *shape* alpha 'shape_alpha' separately
            shape = Shape(st, g, c, fd, shape_alpha, lt, ls, rt, tp, ahs)
            # No need to restore alpha separately, it's handled by passing shape_alpha to constructor
            return shape
        except Exception as e:
            print(f"Warning: General error creating Shape instance from dict: {e}, data: {data}")
            traceback.print_exc()
            return None


# --- Klasa DesktopOverlayRgn ---
class DesktopOverlayRgn(QWidget):
    drawing_mode_changed = Signal(bool)
    color_changed = Signal(QColor) # Signal for normal mode color change
    board_color_changed = Signal(QColor) # Signal for board mode color change
    # Signal to update control panel defaults (e.g., when text is edited)
    defaults_changed = Signal()

    # --- Global Hotkey Handling (Windows specific) ---
    def _register_global_hotkey(self):
        if not _IS_WINDOWS:
             print("Skipping global hotkey registration (Not Windows)")
             return False
        # Try to get HWND if not already available
        if not self.hwnd:
             self.hwnd = self.winId() # Try getting it now
        if not self.hwnd:
            print("Cannot register global hotkey (HWND not available yet)")
            # Try again later after window is definitely shown
            QTimer.singleShot(200, self._register_global_hotkey)
            return False

        registered_count = 0
        failed_keys = []

        # --- Define Hotkeys (Alt + F1/F2/F3) ---
        hotkeys_to_register = [
            {"id": HOTKEY_ID_ALT_F1, "vk": 0x70, "name": "Alt+F1"},  # VK_F1
            {"id": HOTKEY_ID_ALT_F2, "vk": 0x71, "name": "Alt+F2"},  # VK_F2
            {"id": HOTKEY_ID_ALT_F3, "vk": 0x72, "name": "Alt+F3"},  # VK_F3
        ]
        modifiers = MOD_ALT # Use Alt modifier

        for hotkey in hotkeys_to_register:
            hotkey_id = hotkey["id"]
            vk_key = hotkey["vk"]
            key_name = hotkey["name"]

            print(f"Attempting to register {key_name} (ID: {hotkey_id}, VK: {vk_key}, Mod: {modifiers}, HWND: {self.hwnd})")
            if RegisterHotKey(self.hwnd, hotkey_id, modifiers, vk_key):
                print(f"  Global hotkey {key_name} registered successfully.")
                registered_count += 1
            else:
                err = ctypes.GetLastError()
                print(f"  Failed to register global hotkey {key_name}. Error code: {err}")
                # Check if already registered by another app
                if err == 1409: # ERROR_HOTKEY_ALREADY_REGISTERED
                     # Display only one warning for all failed registrations
                     if not failed_keys:
                         QMessageBox.warning(self, "Hotkey Error", f"Could not register one or more hotkeys ({key_name}, potentially others).\nThey might be in use by another application.")
                failed_keys.append(key_name)

        if failed_keys:
             print(f"Summary: Failed to register hotkeys: {', '.join(failed_keys)}")
        if registered_count > 0:
             print(f"Summary: Successfully registered {registered_count} hotkeys.")

        return registered_count > 0 # Return True if at least one succeeded

    def _unregister_global_hotkey(self):
        if _IS_WINDOWS and self.hwnd:
            hotkey_ids_to_unregister = [HOTKEY_ID_ALT_F1, HOTKEY_ID_ALT_F2, HOTKEY_ID_ALT_F3]
            for hotkey_id in hotkey_ids_to_unregister:
                print(f"Unregistering global hotkey ID {hotkey_id} for HWND {self.hwnd}.")
                UnregisterHotKey(self.hwnd, hotkey_id)

    def nativeEvent(self, eventType, message):
        # Process Windows messages for global hotkeys
        if _IS_WINDOWS and eventType == "windows_generic_MSG":
            if message:
                try:
                    # Cast message pointer to MSG structure
                    # Check if message is an integer (pointer address) or an object with __int__
                    msg_ptr = message if isinstance(message, int) else message.__int__()
                    msg = ctypes.wintypes.MSG.from_address(msg_ptr)

                    if msg.message == 0x0312: # WM_HOTKEY
                        hotkey_id = msg.wParam
                        print(f"Native Event: WM_HOTKEY detected! ID: {hotkey_id}, wParam={msg.wParam}, lParam={msg.lParam}") # DEBUG
                        if hotkey_id == HOTKEY_ID_ALT_F1:
                            print("Global Hotkey Alt+F1 detected! Toggling drawing mode.")
                            self.set_drawing_mode(not self.drawing_mode)
                            #QApplication.processEvents() # Try processing events after action
                            return True, 0 # Indicate event handled
                        elif hotkey_id == HOTKEY_ID_ALT_F2:
                            print("Global Hotkey Alt+F2 detected! Entering EDIT mode.")
                            self.enter_edit_mode()
                            #QApplication.processEvents() # Try processing events after action
                            return True, 0 # Indicate event handled
                        elif hotkey_id == HOTKEY_ID_ALT_F3:
                            print("Global Hotkey Alt+F3 detected! Entering BOARD mode.")
                            self.enter_board_mode()
                            #QApplication.processEvents() # Try processing events after action
                            return True, 0 # Indicate event handled
                        else:
                            print(f"Unmatched hotkey ID: {hotkey_id}")
                except Exception as e:
                    print(f"Error processing native event message: {e}")
                    traceback.print_exc() # Log error with stack trace
        # Return default processing for other messages or errors
        return super().nativeEvent(eventType, message)
    # --- End Global Hotkey Handling ---


    def __init__(self):
        super().__init__()
        self.hwnd = None
        self.drawing_mode = False
        self.board_mode = False # Flag for whiteboard mode
        self.shapes = []
        self.undo_stack = []
        self.redo_stack = []
        self.current_drawing_shape = None
        self.drag_start_pos = None
        self.drag_start_geometries = {} # Store original geometries for undo/drag/resize
        self.resize_handle = None # e.g., 'top_left', 'vertex_0'
        self.polygon_points = [] # Points for polygon or line_point being drawn
        self.brush_points = [] # Points for the brush stroke being drawn
        self.handle_size = 8 # Size of resize handles
        self.current_tool = "rect" # Default tool
        self.control_panel_visible = True
        self.pressed_keys = set() # Track currently pressed keys
        self.control_panel = None # Reference to the control panel widget
        self.last_esc_press_time = 0 # For double-press detection
        self.settings = QSettings("MyCompany", "DesktopOverlayRGN") # For BOARD settings

        # --- State Variables ---
        self.resizing = False
        self.dragging = False
        self.selected_shapes = []
        self.clipboard_shapes = [] # For copy/paste

        # --- Normal Drawing Mode Settings (Linked to Control Panel) ---
        self.current_pen_color = QColor(255, 0, 0) # Default red
        self.current_alpha = 255
        self.current_line_thickness = 2
        self.current_line_style = Qt.SolidLine
        self.current_arrow_head_size = 10
        self.brush_size = 5 # Controlled by control panel
        self.dim_background = True # Flag to control background dimming
        self.show_tool_text = True # Flag to control tool text visibility
        self.background_color_when_drawing = QColor(30, 30, 30, 100) # Used only if dim_background is True

        # --- BOARD Mode Settings (Independent of Control Panel) ---
        self.board_background_color = QColor(Qt.white) # Default board bg (opaque white)
        self.current_pen_color_board = QColor(Qt.black) # Default board pen (opaque black)
        # Default text properties for BOARD mode (can differ from normal)
        self.board_default_text_properties = {
            'text': '', 'font': 'Arial', 'size': 14, 'bold': False, 'italic': False,
            'underline': False, 'strikeout': False, 'color': '#000000',
            'background_color': None, 'alignment': 'left'
        }
        self.show_indicators_in_board_mode = True # Store show_tool_text state for board mode

        # Color map for numeric key shortcuts (NORMAL mode)
        self.color_shortcuts = {
            Qt.Key_0: QColor("black"), Qt.Key_1: QColor("white"),
            Qt.Key_2: QColor("cyan"), Qt.Key_3: QColor("gray"),
            Qt.Key_4: QColor("red"), Qt.Key_5: QColor("orange"),
            Qt.Key_6: QColor("yellow"), Qt.Key_7: QColor("green"),
            Qt.Key_8: QColor("blue"), Qt.Key_9: QColor("magenta")
        }
        # Color map for numeric/Alt+numeric key shortcuts (BOARD mode)
        self.board_color_shortcuts = { # Same colors, different application logic
            Qt.Key_0: QColor("black"), Qt.Key_1: QColor("white"),
            Qt.Key_2: QColor("cyan"), Qt.Key_3: QColor("gray"),
            Qt.Key_4: QColor("red"), Qt.Key_5: QColor("orange"),
            Qt.Key_6: QColor("yellow"), Qt.Key_7: QColor("green"),
            Qt.Key_8: QColor("blue"), Qt.Key_9: QColor("magenta")
        }

        # Default text properties (NORMAL mode - loaded/saved by control panel)
        self.default_text_properties = {
            'text': '', 'font': 'Arial', 'size': 12, 'bold': False, 'italic': False,
            'underline': False, 'strikeout': False, 'color': '#000000',
            'background_color': None, 'alignment': 'left'
        }

        self.setup_window_properties()
        self.load_board_settings() # Load board settings early
        QTimer.singleShot(150, self._get_hwnd) # Delay HWND grab slightly
        print("Overlay RGN initialized...")


    def setup_window_properties(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        # Set WA_TranslucentBackground always True initially, control actual transparency in paintEvent/configure_mode
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowTransparentForInput, True) # Start transparent
        self.setMouseTracking(True) # Needed to check cursor position for handles etc. even when not dragging
        try:
            virtual_desktop_geometry = QGuiApplication.primaryScreen().virtualGeometry()
            self.setGeometry(virtual_desktop_geometry)
            print(f"Overlay geometry set to virtual desktop: {virtual_desktop_geometry}")
        except Exception as e:
            print(f"Error setting virtual desktop geometry: {e}")
            try:
                screen_geometry = QGuiApplication.primaryScreen().geometry()
                self.setGeometry(screen_geometry)
                print(f"Overlay geometry set to primary screen: {screen_geometry}")
            except Exception as e2:
                 print(f"Error setting primary screen geometry: {e2}")
                 self.setGeometry(0,0, 1024, 768) # Fallback geometry
                 print("Overlay geometry set to fallback 1024x768")

    def _get_hwnd(self):
        print("Attempting to get HWND...")
        if not _IS_WINDOWS:
            print("Non-Windows system, skipping HWND")
            self.drawing_mode = False
            self._configure_mode() # Configure non-drawing mode
            self.show()
            return
        try:
            # winId() needs the window to be created, ensure it is.
            # Using effectiveWinId() might be more robust after show().
            if not self.testAttribute(Qt.WA_WState_Created):
                self.create() # Force window creation if not done yet

            self.hwnd = self.winId()
            if not self.hwnd:
                # Retry after showing, as winId might be valid then
                print("Failed to get HWND immediately, will try again after show().")
                QTimer.singleShot(100, self._get_hwnd)
                if not self.isVisible(): self.show() # Show window to ensure it's created
                return

            print(f"Successfully obtained HWND: {self.hwnd}")
            # --- Register hotkeys only AFTER HWND is confirmed ---
            self._register_global_hotkey()
            # --- ---
            self._configure_mode() # Configure initial mode (non-drawing)
            if not self.isVisible(): self.show() # Ensure visible

        except Exception as e:
            print(f"Error getting HWND or showing window: {e}")
            traceback.print_exc() # More detailed error
            # Fallback: Show anyway
            if not self.isVisible(): self.show()


    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            # --- Background ---
            if self.board_mode:
                # Use board_background_color directly (includes alpha)
                # If alpha is very low (effectively transparent), draw a minimal non-opaque color to allow clicks
                draw_color = self.board_background_color
                if draw_color.alpha() < 5: # Use a small threshold > 0
                     draw_color = QColor(0, 0, 0, 1) # Minimal visible for interaction
                painter.fillRect(self.rect(), draw_color)
            elif self.drawing_mode:
                if self.dim_background:
                    painter.fillRect(self.rect(), self.background_color_when_drawing)
                else:
                    # Minimal non-opaque background when dimming is off
                    painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
            else:
                # Ensure truly transparent when not drawing
                painter.fillRect(self.rect(), Qt.transparent)


            # --- Draw Indicators ---
            if self.drawing_mode:
                # Determine if any indicators should be shown based on board mode and settings
                show_any_indicator = (self.board_mode and self.show_indicators_in_board_mode) or \
                                     (not self.board_mode and self.show_tool_text)

                if show_any_indicator:
                    font = QFont("Arial", 12)
                    painter.setFont(font)
                    metrics = QFontMetrics(font)
                    # Choose indicator colors based on background brightness (or fixed)
                    bg_is_dark = False
                    if self.board_mode:
                        effective_bg_color = self.board_background_color
                        if effective_bg_color.alpha() < 5: bg_is_dark = False
                        else: bg_is_dark = effective_bg_color.lightnessF() < 0.5
                    elif self.dim_background: bg_is_dark = True

                    indicator_bg_color = QColor(0, 0, 0, 180) if not bg_is_dark else QColor(255, 255, 255, 180)
                    indicator_text_color = QColor(255, 255, 0, 200) if not bg_is_dark else QColor(0, 0, 128, 200) # Yellow on dark, Dark Blue on light
                    board_text_color = QColor(255, 100, 100, 200) if not bg_is_dark else QColor(128, 0, 0, 200) # Reddish on dark, Dark Red on light
                    color_indicator_border_color = QColor(Qt.white) if not bg_is_dark else QColor(Qt.black)


                    # --- Draw Tool Name & Color Indicator (Top-Left) ---
                    tool_name_text = f"{self.current_tool.upper()}"
                    tool_name_rect = metrics.boundingRect(QRect(0, 0, 500, 100), Qt.AlignLeft | Qt.AlignVCenter, tool_name_text)
                    tool_name_height = tool_name_rect.height()

                    # Color indicator square size and position
                    color_indicator_size = tool_name_height # Square height matches text height
                    color_indicator_spacing = 4 # Space between indicator and text
                    indicator_x_start = 5 + color_indicator_size + color_indicator_spacing

                    # Tool name position & background (shifted right for color indicator)
                    tool_name_pos = QPointF(indicator_x_start, 5 + metrics.ascent())
                    tool_name_bg_rect = QRectF(
                        QPointF(indicator_x_start - 4, 5), # Start background slightly left of text
                        QSizeF(tool_name_rect.width() + 8, tool_name_height + 6) # Padding
                    )

                    painter.save()
                    # Draw tool text background
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(indicator_bg_color)
                    painter.drawRoundedRect(tool_name_bg_rect, 3, 3)
                    # Draw tool text
                    painter.setPen(indicator_text_color)
                    painter.drawText(tool_name_pos, tool_name_text)
                    painter.restore()

                    # Draw Color Indicator Square
                    painter.save()
                    indicator_color = self.current_pen_color_board if self.board_mode else self.current_pen_color
                    indicator_rect = QRectF(5, 5 + 3, color_indicator_size, color_indicator_size) # Position at top-left (adjust Y slightly)
                    painter.setBrush(indicator_color)
                    painter.setPen(QPen(color_indicator_border_color, 1)) # Add border
                    painter.drawRect(indicator_rect)
                    painter.restore()
                    # --- End Tool Name & Color Indicator ---


                    # Draw BOARD Indicator (Top-Right) only if in board/edit mode
                    if self.board_mode:
                        # Indicate EDIT mode specifically
                        board_text = "EDIT MODE" if self.board_background_color.alpha() < 5 else "BOARD" # Changed threshold from 0 to <5
                        board_rect = metrics.boundingRect(QRect(0, 0, 500, 100), Qt.AlignRight | Qt.AlignVCenter, board_text)
                        board_bg_width = board_rect.width() + 8
                        board_bg_height = board_rect.height() + 6
                        board_bg_x = self.width() - board_bg_width - 5
                        board_bg_y = 5
                        board_pos = QPointF(board_bg_x + 4, board_bg_y + metrics.ascent()) # Text position inside bg rect
                        board_bg_rect = QRectF(board_bg_x, board_bg_y, board_bg_width, board_bg_height)


                        painter.save()
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(indicator_bg_color)
                        painter.drawRoundedRect(board_bg_rect, 3, 3)
                        painter.setPen(board_text_color)
                        painter.drawText(board_pos, board_text)
                        painter.restore()
            # --- End Draw Indicators ---


            # Draw existing shapes
            for shape in self.shapes:
                if shape and shape.geometry:
                    is_selected = shape in self.selected_shapes
                    self.draw_shape(painter, shape, is_selected)

            # Draw preview of shape being created
            if self.drawing_mode and self.current_drawing_shape:
                self.draw_shape(painter, self.current_drawing_shape, is_preview=True)

            # Draw polygon/line_point helper lines
            if self.drawing_mode and self.current_tool in ['polygon', 'line_point'] and self.polygon_points:
                pen = QPen(QColor(0, 255, 255, 150), 1, Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                if len(self.polygon_points) > 1:
                    painter.drawPolyline(QPolygonF(self.polygon_points))
                # Draw small circles at vertices
                painter.setBrush(QColor(0, 255, 255, 100))
                for point in self.polygon_points:
                    painter.drawEllipse(point, 3, 3)
                # Draw line from last point to cursor
                if len(self.polygon_points) >= 1:
                    current_pos = self.mapFromGlobal(QCursor.pos())
                    painter.drawLine(self.polygon_points[-1], current_pos)

            # Draw resize handles and rotation info for selected shapes
            if self.drawing_mode and self.selected_shapes:
                is_rotating = (Qt.Key_Left in self.pressed_keys or Qt.Key_Right in self.pressed_keys) and \
                              (QGuiApplication.keyboardModifiers() & Qt.AltModifier)

                for shape in self.selected_shapes:
                    if shape and shape.geometry:
                        self.draw_resize_handles(painter, shape)
                        if is_rotating:
                            painter.save()
                            angle_font = QFont("Arial", 20)
                            painter.setFont(angle_font)

                            center = QPointF()
                            geo = shape.geometry
                            if isinstance(geo, QRectF) and geo.isValid():
                                center = geo.center()
                            elif isinstance(geo, list):
                                valid_points = [p for p in geo if isinstance(p, QPointF)]
                                if valid_points:
                                    center = QPointF(sum(p.x() for p in valid_points)/len(valid_points), sum(p.y() for p in valid_points)/len(valid_points))

                            if not center.isNull():
                                absolute_angle = shape.rotation % 360
                                rotation_text = ""
                                orient_angle_deg = 0.0 # Default for non-lines

                                # --- Start Universal Angle Calculation ---
                                if shape.type in ['line', 'arrow'] and isinstance(geo, list) and len(geo) == 2:
                                    p1, p2 = geo
                                    if isinstance(p1, QPointF) and isinstance(p2, QPointF):
                                        delta = p2 - p1
                                        if delta.manhattanLength() > 1e-6:
                                            angle_rad = math.atan2(delta.y(), delta.x())
                                            # Orientation is angle relative to positive Y axis (0 degrees = up)
                                            orient_angle_deg = (math.degrees(angle_rad) + 90) % 360
                                else:
                                    # For other shapes, treat base orientation as 0 (aligned with axes)
                                    orient_angle_deg = 0.0

                                sum_angle = (orient_angle_deg + absolute_angle) % 360
                                rotation_text = f"[{orient_angle_deg:.1f}, {absolute_angle:.1f}, {sum_angle:.1f}]"
                                # --- End Universal Angle Calculation ---


                                metrics = QFontMetrics(angle_font)
                                text_rect = metrics.boundingRect(
                                    QRect(0, 0, 500, 500),
                                    int(Qt.AlignLeft),
                                    rotation_text
                                )
                                text_pos = center + QPointF(15, -15 - text_rect.height()/2)

                                screen_rect = self.rect().adjusted(10, 10, -10, -10)
                                text_draw_rect = QRectF(
                                    text_pos - QPointF(0, metrics.ascent()),
                                    QSizeF(text_rect.width(), text_rect.height())
                                ).adjusted(-4, -3, 4, 3)

                                # Keep text within bounds
                                if text_draw_rect.right() > screen_rect.right():
                                    text_pos.setX(screen_rect.right() - text_draw_rect.width() -4) # Adjust X too
                                if text_draw_rect.left() < screen_rect.left():
                                    text_pos.setX(screen_rect.left() + 4)
                                if text_draw_rect.top() < screen_rect.top():
                                    text_pos.setY(screen_rect.top() + metrics.ascent() + 3)
                                if text_draw_rect.bottom() > screen_rect.bottom():
                                    text_pos.setY(screen_rect.bottom() - (text_draw_rect.height() - metrics.ascent())) # Adjust Y


                                bg_rect = QRectF(
                                    text_pos - QPointF(0, metrics.ascent()),
                                    QSizeF(text_rect.width(), text_rect.height())
                                ).adjusted(-4, -3, 4, 3)

                                # --- Background to opaque black ---
                                painter.setPen(Qt.NoPen)
                                painter.setBrush(QColor(0, 0, 0, 255)) # Opaque Black
                                painter.drawRoundedRect(bg_rect, 5, 5)
                                # --- End Change ---

                                painter.setPen(QColor(255, 255, 0))
                                painter.drawText(text_pos, rotation_text)

                            painter.restore()
                            # --- End Rotation Angle Display ---


        except Exception as e:
             print(f"Error in paintEvent: {e}")
             traceback.print_exc()


    def draw_shape(self, painter, shape, is_selected=False, is_preview=False):
        if not shape or not shape.geometry:
            return

        # Use shape's alpha property for the overall opacity
        shape_alpha = shape.alpha if not is_preview else min(shape.alpha, 100)

        # --- Calculate Pen Color (based on shape color + selection/preview) ---
        pen_color = QColor(shape.color)
        if not pen_color.isValid(): pen_color = QColor(Qt.red) # Fallback

        if is_selected:
            # Use bright cyan for selection, slightly transparent for preview selection
            sel_color = QColor('cyan') if not is_preview else QColor(0, 255, 255, 100)
            pen_color = sel_color # Selection overrides base color for pen
            # Pen alpha is determined by selection state, not shape alpha
            pen_color.setAlpha(255 if not is_preview else 100)
        else:
            # Base pen color on shape's color, apply overall shape alpha
            pen_color.setAlpha(shape_alpha)


        # --- Setup Pen ---
        pen = QPen(pen_color, shape.line_thickness, shape.line_style)
        if shape.type in ['rect', 'ellipse', 'triangle', 'polygon']:
            pen.setJoinStyle(Qt.MiterJoin)
        else: # Lines, brushes etc.
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)

        # --- Custom DotLine workaround ---
        if shape.line_style == Qt.DotLine:
            # Ensure dots are visible regardless of thickness
            dash_len = 1
            gap_len = max(2, shape.line_thickness * 1.5)
            pen.setDashPattern([dash_len, gap_len])
            pen.setCapStyle(Qt.RoundCap) # Crucial for round dots

        # --- Setup Brush ---
        brush = Qt.NoBrush # Default to no fill
        if shape.filled:
            brush_color = QColor(shape.color) # Start with shape's base color
            if not brush_color.isValid(): brush_color = QColor(Qt.red) # Fallback
            # Apply overall shape alpha to brush
            brush_color.setAlpha(shape_alpha)
            brush = QBrush(brush_color)


        geo = shape.geometry

        # --- Save Painter State ---
        painter.save()

        # --- Apply Pen and Brush ---
        painter.setPen(pen)
        painter.setBrush(brush)

        # --- Apply Rotation Transform ---
        center = QPointF()
        if isinstance(geo, QRectF) and geo.isValid():
            center = geo.center()
        elif isinstance(geo, list):
            valid_points = [p for p in geo if isinstance(p, QPointF)]
            if valid_points:
                center = QPointF(sum(p.x() for p in valid_points) / len(valid_points),
                                 sum(p.y() for p in valid_points) / len(valid_points))

        if shape.rotation != 0 and not center.isNull():
            painter.translate(center.x(), center.y())
            painter.rotate(shape.rotation)
            painter.translate(-center.x(), -center.y())
        # --- End Apply Rotation Transform ---


        # --- Draw Specific Shape Types ---
        try:
            if shape.type in ['rect', 'ellipse'] and isinstance(geo, QRectF):
                if not geo.isValid(): return # Don't draw invalid rects
                if shape.type == 'rect':
                    painter.drawRect(geo)
                else:
                    painter.drawEllipse(geo)

            elif shape.type in ['triangle', 'polygon'] and isinstance(geo, list):
                valid_geo = [p for p in geo if isinstance(p, QPointF)]
                if len(valid_geo) >= 3:
                    painter.drawPolygon(QPolygonF(valid_geo))

            elif shape.type in ['brush', 'line_point'] and isinstance(geo, list): # Added line_point
                valid_geo = [p for p in geo if isinstance(p, QPointF)]
                if len(valid_geo) >= 1:
                    # For brush/line_point, use the pen settings derived earlier
                    # but ensure brush is not used for the line itself
                    painter.setBrush(Qt.NoBrush)
                    # Re-apply pen (might have been changed by text BG)
                    painter.setPen(pen)

                    if len(valid_geo) > 1:
                        painter.drawPolyline(QPolygonF(valid_geo))
                    elif len(valid_geo) == 1: # Draw single point as small circle
                        radius = shape.line_thickness / 2.0
                        # Fill single point with the adjusted pen color
                        point_brush_color = QColor(pen.color()) # Use calculated pen color (with alpha)
                        painter.setBrush(point_brush_color)
                        painter.drawEllipse(valid_geo[0], radius, radius)


            elif shape.type in ['line', 'arrow'] and isinstance(geo, list) and len(geo) == 2:
                p1, p2 = geo
                if isinstance(p1, QPointF) and isinstance(p2, QPointF):
                    # Use the calculated pen for the line
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(pen)

                    delta = p2 - p1
                    length = math.sqrt(delta.x()**2 + delta.y()**2)
                    p2_line_end = p2

                    # Shorten line for arrow head
                    if shape.type == 'arrow' and shape.arrow_head_size and shape.arrow_head_size > 0 and length > 1e-6:
                        norm_delta = delta / length
                        arrow_size = shape.arrow_head_size
                        # Approximate shortening based on head size and angle
                        shorten_dist = arrow_size * 0.5 # Adjust as needed
                        shorten_amount = min(max(0, shorten_dist), length * 0.95) # Avoid over-shortening
                        # Only shorten if shorten_amount is positive
                        if shorten_amount > 0:
                            p2_line_end = p2 - norm_delta * shorten_amount

                    painter.drawLine(p1, p2_line_end)

                    # Draw arrow head
                    if shape.type == 'arrow' and shape.arrow_head_size and shape.arrow_head_size > 0:
                        if length > 1e-6:
                            angle_rad = math.atan2(delta.y(), delta.x())
                            arrow_size = shape.arrow_head_size
                            a1_rad = angle_rad + math.radians(150) # Wing angle
                            a2_rad = angle_rad - math.radians(150) # Other wing angle
                            p_wing1 = p2 + QPointF(math.cos(a1_rad) * arrow_size, math.sin(a1_rad) * arrow_size)
                            p_wing2 = p2 + QPointF(math.cos(a2_rad) * arrow_size, math.sin(a2_rad) * arrow_size)

                            painter.save()
                            # Use the calculated pen color (which includes overall alpha) for the head
                            head_brush_color = QColor(pen.color())
                            painter.setBrush(QBrush(head_brush_color))
                            painter.setPen(Qt.NoPen) # No border for head
                            painter.drawPolygon(QPolygonF([p2, p_wing1, p_wing2]))
                            painter.restore()

            elif shape.type == 'text' and isinstance(geo, QRectF) and shape.text_properties:
                if not geo.isValid(): return # Don't draw invalid text rects
                # Use deepcopy to avoid modifying original during drawing if properties change unexpectedly
                props = deepcopy(shape.text_properties)
                text = props.get('text', '')
                if text:
                    try:
                        font = QFont(props.get('font', 'Arial'), props.get('size', 12))
                        font.setBold(props.get('bold', False))
                        font.setItalic(props.get('italic', False))
                        font.setUnderline(props.get('underline', False))
                        font.setStrikeOut(props.get('strikeout', False))
                        painter.setFont(font)

                        # --- Text Color ---
                        text_color = QColor(props.get('color', '#000000'))
                        if not text_color.isValid(): text_color = Qt.black
                        # Apply overall shape alpha to text color
                        text_color.setAlpha(shape_alpha)
                        text_pen = QPen(text_color)

                        # --- Background Color ---
                        bg_color_str = props.get('background_color')
                        has_background = False
                        if bg_color_str:
                            bg_color = QColor(bg_color_str)
                            # Check validity AND alpha > 0 for background drawing
                            if bg_color.isValid() and bg_color.alpha() > 0:
                                # Apply shape's overall alpha to background color's alpha
                                final_bg_alpha_float = (bg_color.alphaF() * (shape_alpha / 255.0))
                                bg_color.setAlphaF(final_bg_alpha_float)
                                # Only draw background if final alpha is significant
                                if bg_color.alpha() > 1:
                                    painter.setBrush(QBrush(bg_color)) # Set brush BEFORE drawing rect
                                    painter.setPen(Qt.NoPen) # No border for background rect
                                    if geo.width() > 0 and geo.height() > 0:
                                         # Draw background rectangle first
                                         painter.drawRect(geo)
                                         has_background = True
                                    else: print(f"Invalid geometry for background: {geo}")

                        # Ensure brush is reset if no background drawn
                        if not has_background:
                             painter.setBrush(Qt.NoBrush)

                        # --- Draw Text ---
                        # Set pen *after* potential background drawing
                        painter.setPen(text_pen)
                        flags = Qt.TextWordWrap
                        align_str = props.get('alignment', 'left')
                        if align_str == 'left': flags |= Qt.AlignLeft
                        elif align_str == 'center': flags |= Qt.AlignCenter
                        elif align_str == 'right': flags |= Qt.AlignRight
                        elif align_str == 'justify': flags |= Qt.AlignJustify
                        # Add vertical alignment
                        flags |= Qt.AlignVCenter

                        # Draw text within the shape's geometry rect
                        painter.drawText(geo, flags, text)
                    except Exception as e:
                        print(f"Error drawing text content: {e}")
                        traceback.print_exc()

        except Exception as e:
            print(f"Error drawing shape type {shape.type}: {e}")
            traceback.print_exc()

        finally:
            painter.restore()


    def draw_resize_handles(self, painter, shape):
        if not shape or not shape.geometry: return
        geo = shape.geometry
        handles_data = [] # List of (handle_name, position) tuples
        transform = QTransform()
        center = QPointF()

        # Calculate center and transformation for rotation
        if isinstance(geo, QRectF) and geo.isValid(): center = geo.center()
        elif isinstance(geo, list):
            valid_points = [p for p in geo if isinstance(p, QPointF)]
            if valid_points: center = QPointF(sum(p.x() for p in valid_points)/len(valid_points), sum(p.y() for p in valid_points)/len(valid_points))

        if shape.rotation != 0 and not center.isNull():
            transform.translate(center.x(), center.y())
            transform.rotate(shape.rotation)
            transform.translate(-center.x(), -center.y())

        # --- Define Handle Positions ---
        if isinstance(geo, QRectF) and geo.isValid():
            # Corner handles
            corners = [geo.topLeft(), geo.topRight(), geo.bottomRight(), geo.bottomLeft()]
            rotated_corners = [transform.map(p) for p in corners]
            handle_names = ['top_left', 'top_right', 'bottom_right', 'bottom_left']
            handles_data.extend(zip(handle_names, rotated_corners))

        elif isinstance(geo, list): # Handles for polygon/line/brush vertices
            valid_points = [p for p in geo if isinstance(p, QPointF)]
            if valid_points:
                rotated_vertices = [transform.map(p) for p in valid_points]
                handles_data.extend([(f'vertex_{i}', p) for i, p in enumerate(rotated_vertices)])

        # --- Draw the Handles ---
        if handles_data:
            painter.setPen(QPen(QColor(0, 255, 0), 1))
            painter.setBrush(QBrush(QColor(0, 255, 0, 180)))
            handle_size_f = float(self.handle_size)
            offset = handle_size_f / 2.0
            for handle_name, pos in handles_data:
                handle_rect = QRectF(pos.x() - offset, pos.y() - offset, handle_size_f, handle_size_f)
                painter.drawRect(handle_rect)

    # --- Slot definitions and other methods follow ---
    @Slot(bool)
    def set_drawing_mode(self, enabled):
        if self.drawing_mode == enabled:
            return

        # Prevent exiting drawing mode if cancelling board mode exit fails
        if not enabled and self.board_mode:
            if not self.exit_board_mode(ask_save=False, configure=False): # Auto-save now, configure later
                if self.control_panel:
                    # Ensure button stays checked if exit is cancelled
                    self.control_panel.update_draw_button_state(True)
                return # Cancelled exit

        self.drawing_mode = enabled
        print(f"Drawing mode set to: {self.drawing_mode}")

        # Reset states only if entering/exiting normal drawing mode
        # These should be reset regardless of board mode when entering/exiting drawing
        self.selected_shapes = []
        self.current_drawing_shape = None
        self.polygon_points = []
        self.brush_points = []
        self.resizing = False
        self.dragging = False
        self.drag_start_pos = None
        self.drag_start_geometries = {}
        self.resize_handle = None

        # Reapply non-board settings when enabling drawing mode (if not in board mode)
        if enabled and not self.board_mode and self.control_panel:
            # Ensure overlay settings match control panel when entering normal drawing mode
            self.dim_background = self.control_panel.dim_check.isChecked()
            self.show_tool_text = self.control_panel.tool_text_check.isChecked()
            print(f"Reapplied settings: dim_background={self.dim_background}, show_tool_text={self.show_tool_text}")

        # Call configure immediately
        self._configure_mode() # Configure mode updates button styles too
        # Ensure UI updates after potential event loop processing
        QTimer.singleShot(0, self.update)

        self.drawing_mode_changed.emit(self.drawing_mode)
        QApplication.processEvents() # Process events to reflect changes immediately


    @Slot(QColor)
    def set_pen_color(self, color):
        """Sets the pen color for NORMAL drawing mode."""
        if isinstance(color, QColor) and color.isValid():
            if color != self.current_pen_color:
                self.current_pen_color = color
                print(f"NORMAL Pen color set to: {color.name(QColor.HexArgb)}")
                self.color_changed.emit(color) # Emit signal for UI update
                self.update() # Update indicator immediately
        else:
            print(f"Received invalid color for normal pen: {color}")

    # --- Board Mode Pen Color (No Slot, set internally or via shortcuts) ---
    def set_board_pen_color(self, color):
        """Sets the pen color for BOARD drawing mode."""
        if isinstance(color, QColor) and color.isValid():
            if color != self.current_pen_color_board:
                self.current_pen_color_board = color
                print(f"BOARD Pen color set to: {color.name(QColor.HexArgb)}")
                self.board_color_changed.emit(color) # Emit signal for board color change
                self.update() # Update indicator immediately
        else:
            print(f"Received invalid color for board pen: {color}")

    @Slot(int)
    def set_alpha(self, alpha):
        """Sets the alpha for shapes."""
        alpha = max(0, min(255, alpha))
        if alpha != self.current_alpha:
            self.current_alpha = alpha
            print(f"Alpha set to: {self.current_alpha}")
            # Update alpha of selected shapes? Optional.
            # if self.selected_shapes: ...

    @Slot(bool)
    def set_dim_background(self, dim_enabled):
        """Sets whether the background is dimmed in NORMAL drawing mode."""
        if self.dim_background != dim_enabled:
            self.dim_background = dim_enabled
            print(f"Background dimming set to: {self.dim_background}")
            # Update visuals only if currently in normal drawing mode
            if not self.board_mode and self.drawing_mode:
                self._configure_mode() # Reconfigure might change opacity attributes
                self.update()

    @Slot(int)
    def set_line_thickness(self, thickness):
        """Sets the line thickness."""
        thickness = max(1, thickness) # Ensure minimum 1
        if thickness != self.current_line_thickness:
            self.current_line_thickness = thickness
            print(f"Line thickness set to: {self.current_line_thickness}")
            # Update selected shapes? Optional.

    @Slot(int)
    def set_line_style(self, style_id):
        """Sets the current line style based on Qt.PenStyle value."""
        new_style = Qt.SolidLine # Default
        try:
            new_style = Qt.PenStyle(style_id)
        except ValueError:
            print(f"Warning: Invalid style ID: {style_id}. Using SolidLine.")

        if new_style != self.current_line_style:
            self.current_line_style = new_style
            print(f"Line style set to: {self.current_line_style} (ID: {style_id})")
            # Update selected shapes? Optional.

    @Slot(int)
    def set_arrow_head_size(self, size):
        """Sets the arrow head size."""
        size = max(1, size)
        if size != self.current_arrow_head_size:
            self.current_arrow_head_size = size
            print(f"Arrow head size set to: {self.current_arrow_head_size}")
            # Update selected arrows immediately?
            if self.selected_shapes:
                changed = False
                for shape in self.selected_shapes:
                    if shape.type == 'arrow':
                        shape.arrow_head_size = self.current_arrow_head_size
                        changed = True
                if changed:
                    self.update()

    @Slot(dict)
    def update_default_text_properties(self, new_defaults):
        """Slot to update default text properties from control panel (Normal mode)."""
        self.default_text_properties.update(new_defaults)
        print("Default text properties updated (Normal mode).")

    @Slot(bool)
    def set_show_tool_text(self, show):
        """Slot to set whether the tool text/indicators are shown."""
        if self.show_tool_text != show:
            self.show_tool_text = show
            print(f"Show indicators set to: {self.show_tool_text}")
            # Update show_indicators_in_board_mode if currently in board mode
            if self.board_mode:
                self.show_indicators_in_board_mode = show
            self.update() # Trigger repaint to show/hide text

    # --- Board Mode / Edit Mode ---

    def _enter_board_or_edit_mode(self, edit_mode=False):
        """Common logic for entering BOARD or EDIT mode."""
        mode_name = "EDIT" if edit_mode else "BOARD"
        print(f"Entering {mode_name} mode")
        self.board_mode = True
        self.dim_background = False # Never dim in these modes
        self.load_board_settings() # Load saved settings (pen/bg color+alpha/text defaults)

        if edit_mode:
            # Override background to be *almost* transparent for EDIT mode
            # Alpha=1 ensures the window is still interactive
            self.board_background_color = QColor(0, 0, 0, 1)
            print("Setting EDIT mode transparent background (alpha=1).")
        else:
            # Ensure BOARD starts opaque white if no settings saved or saved was *almost* transparent
            if self.board_background_color.alpha() < 5: # Use small threshold
                 self.board_background_color = QColor(Qt.white)
                 print("BOARD mode started with transparent saved BG, defaulting to white.")


        # Store current tool text visibility state from control panel setting
        self.show_indicators_in_board_mode = self.show_tool_text

        # Make sure drawing mode is enabled
        if not self.drawing_mode:
            # This will trigger _configure_mode via set_drawing_mode
            self.set_drawing_mode(True)
        else:
            # Already in drawing mode, just need to update visuals/config
            self._configure_mode() # configure_mode updates color button style
            self.update()

    @Slot()
    def enter_board_mode(self):
        self._enter_board_or_edit_mode(edit_mode=False)

    @Slot()
    def enter_edit_mode(self):
        self._enter_board_or_edit_mode(edit_mode=True)

    def exit_board_mode(self, ask_save=False, configure=True): # Changed ask_save default to False
        """Exits BOARD or EDIT mode."""
        if not self.board_mode: return True # Already exited

        # Ask user confirmation about clearing board (keep this)
        reply = QMessageBox.question(self, "Exit Board/Edit Mode",
                                     "Clear the board before exiting?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Cancel) # Default to Cancel

        if reply == QMessageBox.StandardButton.Cancel:
            print("Board/Edit mode exit cancelled.")
            return False # Indicate exit was cancelled

        clear_board = (reply == QMessageBox.StandardButton.Yes)

        print("Exiting BOARD/EDIT mode")
        self.board_mode = False # Set board mode false *before* saving/clearing

        # Always save settings on exit
        self.save_board_settings()

        # Clear shapes if user chose Yes
        if clear_board:
            print("Clearing board.")
            self.clear_scene(save_undo=False) # Clear without adding to undo

        # Restore normal dim setting from control panel if available
        if self.control_panel:
             self.dim_background = self.control_panel.dim_check.isChecked()
        else:
             self.dim_background = True # Default fallback

        # Exit drawing mode completely after exiting board mode
        if configure:
             # This will call _configure_mode
             self.set_drawing_mode(False)
        # If configure is False, the caller (e.g., set_drawing_mode) will handle configuration

        return True # Indicate exit was successful

    def save_board_settings(self):
        """Saves current board-related settings (pen, bg, text defaults)."""
        try:
             self.settings.beginGroup("board")
             self.settings.setValue("penColor", self.current_pen_color_board.name(QColor.HexArgb))
             self.settings.setValue("backgroundColor", self.board_background_color.name(QColor.HexArgb))
             # Save board text defaults
             if hasattr(self, 'board_default_text_properties'):
                 defaults = self.board_default_text_properties
                 self.settings.beginGroup("textDefaults")
                 self.settings.setValue("font", defaults.get('font', 'Arial'))
                 self.settings.setValue("size", defaults.get('size', 14))
                 self.settings.setValue("bold", defaults.get('bold', False))
                 self.settings.setValue("italic", defaults.get('italic', False))
                 self.settings.setValue("underline", defaults.get('underline', False))
                 self.settings.setValue("strikeout", defaults.get('strikeout', False))
                 self.settings.setValue("color", defaults.get('color', '#000000'))
                 self.settings.setValue("backgroundColor", defaults.get('background_color')) # Can be None
                 self.settings.setValue("alignment", defaults.get('alignment', 'left'))
                 self.settings.endGroup() # End textDefaults group
             self.settings.endGroup() # End board group
             self.settings.sync()
             print("BOARD settings (Pen, BG, Text Defaults) saved.")
        except Exception as e: print(f"Error saving BOARD settings: {e}")

    def load_board_settings(self):
        """Loads board-related settings (pen, bg, text defaults)."""
        try:
            self.settings.beginGroup("board")
            # Load pen color, default to opaque black
            pen_color_str = self.settings.value("penColor", QColor(Qt.black).name(QColor.HexArgb))
            self.current_pen_color_board = QColor(pen_color_str)
            if not self.current_pen_color_board.isValid(): self.current_pen_color_board = QColor(Qt.black)

            # Load background color, default to opaque white
            bg_color_str = self.settings.value("backgroundColor", QColor(Qt.white).name(QColor.HexArgb))
            self.board_background_color = QColor(bg_color_str)
            if not self.board_background_color.isValid(): self.board_background_color = QColor(Qt.white)

            # Load board text defaults
            defaults = self.board_default_text_properties # Start with current defaults
            self.settings.beginGroup("textDefaults")
            defaults['font'] = self.settings.value("font", defaults['font'])
            defaults['size'] = self.settings.value("size", defaults['size'], type=int)
            defaults['bold'] = self.settings.value("bold", defaults['bold'], type=bool)
            defaults['italic'] = self.settings.value("italic", defaults['italic'], type=bool)
            defaults['underline'] = self.settings.value("underline", defaults['underline'], type=bool)
            defaults['strikeout'] = self.settings.value("strikeout", defaults['strikeout'], type=bool)
            defaults['color'] = self.settings.value("color", defaults['color'])
            bg_color_setting = self.settings.value("backgroundColor")
            defaults['background_color'] = bg_color_setting if bg_color_setting is not None else None
            defaults['alignment'] = self.settings.value("alignment", defaults['alignment'])
            self.settings.endGroup() # End textDefaults group
            self.board_default_text_properties = defaults # Update overlay's board defaults

            self.settings.endGroup() # End board group
            print("BOARD settings (Pen, BG, Text Defaults) loaded:",
                  f"Pen={self.current_pen_color_board.name(QColor.HexArgb)},",
                  f"BG={self.board_background_color.name(QColor.HexArgb)}")
        except Exception as e:
            print(f"Error loading BOARD settings: {e}")
            # Ensure defaults on error
            self.current_pen_color_board = QColor(Qt.black)
            self.board_background_color = QColor(Qt.white)
            self.board_default_text_properties = { # Reset board text defaults too
                'text': '', 'font': 'Arial', 'size': 14, 'bold': False, 'italic': False,
                'underline': False, 'strikeout': False, 'color': '#000000',
                'background_color': None, 'alignment': 'left'
            }

    # --- End Board Mode / Edit Mode ---


    def _configure_mode(self):
        """Configures window properties based on drawing_mode and board_mode."""
        if not self.isVisible() and not self.testAttribute(Qt.WA_WState_Created):
            print("_configure_mode: Window not visible or created, delaying.")
            QTimer.singleShot(50, self._configure_mode)
            return

        # Ensure HWND is valid if needed
        if _IS_WINDOWS and not self.hwnd:
             self.hwnd = self.winId()
             print(f"_configure_mode: Re-checked HWND: {self.hwnd}")

        self.releaseKeyboard() # Release keyboard focus if held
        self.unsetCursor() # Reset cursor to default arrow

        if self.drawing_mode:
            print("_configure_mode: Entering Drawing Mode Configuration")
            # Make window interactable BEFORE setting focus
            self.setWindowFlag(Qt.WindowTransparentForInput, False)
            # Ensure other flags are maintained
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setMouseTracking(True) # Enable mouse tracking for drawing

            # --- Determine Opacity/Transparency based on mode ---
            is_background_opaque = False
            set_translucent_bg_attr = True

            if self.board_mode:
                # Board mode is opaque ONLY if BG alpha is 255
                is_background_opaque = (self.board_background_color.alpha() == 255)
                set_translucent_bg_attr = not is_background_opaque
            else: # Normal drawing mode
                # Normal mode is opaque ONLY if dimming is ON
                is_background_opaque = self.dim_background
                set_translucent_bg_attr = not is_background_opaque

            # Update attributes - these trigger paint updates
            self.setAttribute(Qt.WA_OpaquePaintEvent, is_background_opaque)
            self.setAttribute(Qt.WA_TranslucentBackground, set_translucent_bg_attr)
            print(f"Configure Drawing Mode: OpaquePaint={is_background_opaque}, TranslucentBG={set_translucent_bg_attr} (Board={self.board_mode}, BGAlpha={self.board_background_color.alpha()}, Dim={self.dim_background})")
            # --- End Opacity Logic ---


            if _IS_WINDOWS and self.hwnd:
                 # Make the whole window clickable when drawing by removing region
                print(f"Setting Window Region to NULL for HWND {self.hwnd}")
                result = SetWindowRgn(self.hwnd, None, True) # True to redraw
                if result == 0: print("SetWindowRgn (NULL) failed!")
            else:
                 print("Skipping SetWindowRgn (Not Windows or HWND invalid)")


            # Set focus AFTER making the window interactable
            self.raise_()
            self.activateWindow()
            self.setFocus(Qt.ActiveWindowFocusReason)
            print("Set focus for drawing mode.")
            # Add a small delay and try setting focus again, might help with hotkey issue
            QTimer.singleShot(50, lambda: self.setFocus(Qt.ActiveWindowFocusReason) if self.drawing_mode else None)

        else: # Configuring Non-Drawing Mode (Always transparent, pass-through)
            print("_configure_mode: Entering Non-Drawing Mode Configuration")
            self.setAttribute(Qt.WA_OpaquePaintEvent, False) # Not opaque
            self.setAttribute(Qt.WA_TranslucentBackground, True) # Translucent BG
            self.setWindowFlag(Qt.WindowTransparentForInput, True) # Pass input through
            # Ensure other flags are maintained
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setMouseTracking(False) # Disable mouse tracking when not drawing

            # For non-drawing mode on Windows, make the window truly transparent to clicks
            # by setting an empty region. (Not needed if WindowTransparentForInput works reliably)
            # if _IS_WINDOWS and self.hwnd:
            #     print(f"Setting Empty Window Region for HWND {self.hwnd}")
            #     empty_region = CreateRectRgn(0, 0, 0, 0)
            #     result = SetWindowRgn(self.hwnd, empty_region, True)
            #     DeleteObject(empty_region) # Clean up region object
            #     if result == 0: print("SetWindowRgn (Empty) failed!")


        # Ensure window is visible and update visuals
        if not self.isVisible(): self.show()
        self.update()
        QApplication.processEvents()
        print("_configure_mode: Configuration finished.")

        # --- Update Control Panel Color Button Visuals ---
        # These now always reflect the stored color for their respective modes
        if self.control_panel:
            self.control_panel.update_draw_color_button_style(self.current_pen_color)
            self.control_panel.update_edit_color_button_style(self.current_pen_color_board)
        # --- ---


    def get_handle_at(self, point):
        """Find which resize handle (if any) is at the given point."""
        # Iterate reversed because selected shapes might overlap handles
        for shape in reversed(self.selected_shapes):
            if not shape or not shape.geometry: continue

            geo = shape.geometry
            handle_size_f = float(self.handle_size)
            # Use a slightly larger radius for easier clicking
            check_radius_sq = (handle_size_f * 0.75)**2

            transform = QTransform()
            center = QPointF()

            # Calculate center and transformation for rotation
            if isinstance(geo, QRectF) and geo.isValid(): center = geo.center()
            elif isinstance(geo, list):
                valid_points = [p for p in geo if isinstance(p, QPointF)]
                if valid_points: center = QPointF(sum(p.x() for p in valid_points)/len(valid_points), sum(p.y() for p in valid_points)/len(valid_points))

            if shape.rotation != 0 and not center.isNull():
                transform.translate(center.x(), center.y())
                transform.rotate(shape.rotation)
                transform.translate(-center.x(), -center.y())

            # Check handles based on geometry type
            if isinstance(geo, QRectF) and geo.isValid():
                corners = [geo.topLeft(), geo.topRight(), geo.bottomRight(), geo.bottomLeft()]
                rotated_corners = [transform.map(p) for p in corners]
                handle_names = ['top_left', 'top_right', 'bottom_right', 'bottom_left']
                for name, pos in zip(handle_names, rotated_corners):
                    delta = pos - point
                    if QPointF.dotProduct(delta, delta) <= check_radius_sq:
                        return (shape, name)

            elif isinstance(geo, list): # Handles for polygon/line/brush vertices
                valid_points = [p for p in geo if isinstance(p, QPointF)]
                if valid_points:
                    rotated_vertices = [transform.map(p) for p in valid_points]
                    for i, pos in enumerate(rotated_vertices):
                        handle_name = f'vertex_{i}'
                        delta = pos - point
                        if QPointF.dotProduct(delta, delta) <= check_radius_sq:
                            return (shape, handle_name)
        return None # No handle found

    def save_state(self, action_type, shapes_involved=None, previous_geometries=None, indices=None, all_shapes_before=None):
        """Saves the current state for undo functionality."""
        # Simplified: Always deepcopy involved shapes for robustness
        involved_before = deepcopy(shapes_involved) if shapes_involved else None
        involved_after = deepcopy(shapes_involved) if shapes_involved and action_type == 'draw' else None # Only for draw

        try:
            state = {
                'action': action_type,
                'involved_shapes_before_action': involved_before if action_type not in ['draw', 'paste'] else None, # Paste stores shapes *before* action
                'involved_shapes_after_action': involved_after if action_type == 'draw' else None,
                # previous_geometries holds specific *properties* before the change OR paste count
                'previous_properties': deepcopy(previous_geometries) if action_type not in ['draw', 'delete', 'delete_selected', 'clear', 'load', 'paste', 'load_join', 'change_board_text_defaults'] else None,
                'original_indices': indices if indices is not None else [],
                'all_shapes_before': deepcopy(all_shapes_before) if action_type in ['clear', 'load'] else None,
                'paste_count': previous_geometries if action_type == 'paste' else None, # Reuse prev_geometries for paste count
                'board_bg_before': None, # For board bg change
                'board_pen_before': None, # For board pen change
                'board_text_defaults_before': previous_geometries.get('board_text_defaults') if action_type == 'change_board_text_defaults' else None, # Store only the defaults dict
            }
            if action_type == 'paste':
                 # Ensure involved_shapes_before_action holds the state *before* paste for undo
                 state['involved_shapes_before_action'] = deepcopy(shapes_involved)


            # Add board state if relevant *before* the change
            if action_type == 'change_board_bg':
                 if state['previous_properties'] and 'board_bg' in state['previous_properties']:
                     state['board_bg_before'] = state['previous_properties']['board_bg']
                 else: print("Warning: Board BG prev color not passed correctly to save_state for undo.")
            if action_type == 'change_board_pen':
                 if state['previous_properties'] and 'board_pen' in state['previous_properties']:
                    state['board_pen_before'] = state['previous_properties']['board_pen']
                 else: print("Warning: Board Pen prev color not passed correctly to save_state for undo.")
            # Note: board_text_defaults_before handled above using previous_geometries


            self.undo_stack.append(state)
            self.redo_stack.clear() # Clear redo stack on new action
            MAX_UNDO = 100
            if len(self.undo_stack) > MAX_UNDO:
                self.undo_stack.pop(0) # Limit undo history size
        except Exception as e:
            print(f"Error saving undo state for action '{action_type}': {e}")
            traceback.print_exc()


    def undo(self):
        if not self.undo_stack:
            print("Undo stack is empty")
            return
        state_to_undo = self.undo_stack.pop()
        action = state_to_undo['action']
        print(f"Undoing action: {action}")

        try:
            # Prepare redo state *before* modifying current state
            redo_state = {
                 'action': action,
                 'involved_shapes_before_undo': deepcopy(self.shapes), # State just before undo
                 'original_indices': deepcopy(state_to_undo.get('original_indices')),
                 'previous_properties_for_redo': deepcopy(state_to_undo.get('previous_properties')), # Store original prev props for redo
                 # Carry over other necessary info
                 'involved_shapes_before_action': deepcopy(state_to_undo.get('involved_shapes_before_action')),
                 'involved_shapes_after_action': deepcopy(state_to_undo.get('involved_shapes_after_action')),
                 'all_shapes_before': deepcopy(state_to_undo.get('all_shapes_before')),
                 'paste_count': state_to_undo.get('paste_count'),
                 'board_bg_before_undo': deepcopy(self.board_background_color) if action == 'change_board_bg' else None,
                 'board_pen_before_undo': deepcopy(self.current_pen_color_board) if action == 'change_board_pen' else None,
                 'board_text_defaults_before_undo': deepcopy(self.board_default_text_properties) if action == 'change_board_text_defaults' else None,
                 'board_bg_before': deepcopy(state_to_undo.get('board_bg_before')),
                 'board_pen_before': deepcopy(state_to_undo.get('board_pen_before')),
                 'board_text_defaults_before': deepcopy(state_to_undo.get('board_text_defaults_before')),
            }


            if action == 'draw':
                indices = state_to_undo.get('original_indices', [])
                if indices and len(indices) == 1:
                    idx = indices[0]
                    if 0 <= idx < len(self.shapes):
                        print(f"Undoing draw by removing shape at index {idx}")
                        self.shapes.pop(idx)
                    else: print(f"Warning: Invalid index {idx} during undo draw.")
                else: print(f"Warning: Cannot reliably undo draw action - missing index.")

            elif action == 'paste':
                # Restore the state *before* the paste operation
                original_shapes = state_to_undo.get('involved_shapes_before_action')
                if original_shapes is not None:
                    print(f"Undoing paste by restoring {len(original_shapes)} shapes.")
                    self.shapes = original_shapes # Restore the list directly
                else: print("Warning: Missing 'involved_shapes_before_action' data for undo paste.")


            elif action in ['delete', 'delete_selected']:
                indices = sorted(state_to_undo.get('original_indices', []), reverse=False)
                shapes_to_reinsert = state_to_undo.get('involved_shapes_before_action', [])
                if len(indices) == len(shapes_to_reinsert):
                    insert_map = sorted(zip(indices, shapes_to_reinsert), key=lambda item: item[0])
                    for index, shape in insert_map:
                         if shape: # Ensure shape is not None
                            if 0 <= index <= len(self.shapes): self.shapes.insert(index, shape)
                            else: self.shapes.append(shape) # Append if index invalid
                         else: print(f"Warning: Tried to reinsert None shape at index {index} during undo delete.")
                else: print(f"Warning: Mismatch indices ({len(indices)})/shapes ({len(shapes_to_reinsert)}) during undo delete.")

            elif action in ['move', 'resize', 'rotate', 'scale', 'change_color', 'change_alpha', 'toggle_fill', 'change_line_style', 'change_line_thickness', 'edit_text', 'change_board_bg', 'change_board_pen', 'change_board_text_defaults']:
                previous_props_map = state_to_undo.get('previous_properties', {})
                original_indices = state_to_undo.get('original_indices', [])

                # Handle board changes first (not tied to indices)
                if action == 'change_board_bg':
                    prev_color = state_to_undo.get('board_bg_before')
                    if prev_color and isinstance(prev_color, QColor):
                        self.board_background_color = prev_color
                        print(f"Undid board background change to {prev_color.name(QColor.HexArgb)}")
                        self._configure_mode() # Reconfigure needed for transparency changes
                    else: print(f"Warning: Missing or invalid previous board background color for undo: {prev_color}")
                elif action == 'change_board_pen':
                    prev_color = state_to_undo.get('board_pen_before')
                    if prev_color and isinstance(prev_color, QColor):
                        self.current_pen_color_board = prev_color
                        self.board_color_changed.emit(prev_color) # Signal change
                        print(f"Undid board pen change to {prev_color.name(QColor.HexArgb)}")
                    else: print(f"Warning: Missing or invalid previous board pen color for undo: {prev_color}")
                elif action == 'change_board_text_defaults':
                     prev_defaults = state_to_undo.get('board_text_defaults_before')
                     if prev_defaults and isinstance(prev_defaults, dict):
                          self.board_default_text_properties = prev_defaults
                          print(f"Undid board text default change to: {prev_defaults}")
                     else: print(f"Warning: Missing or invalid board text defaults for undo: {prev_defaults}")

                # Handle shape property changes
                elif len(original_indices) == len(previous_props_map):
                    indices_restored = 0
                    for original_index in original_indices:
                        if 0 <= original_index < len(self.shapes):
                            target_shape = self.shapes[original_index]
                            props_before = previous_props_map.get(original_index)
                            if props_before is not None:
                                try:
                                     valid_restore = True
                                     if action in ['move', 'resize', 'scale']:
                                         if isinstance(props_before, (QRectF, list)): target_shape.geometry = deepcopy(props_before) # Restore with copy
                                         else: valid_restore = False
                                     elif action == 'rotate':
                                         if isinstance(props_before, (int, float)): target_shape.rotation = props_before
                                         else: valid_restore = False
                                     elif action == 'change_color':
                                         if isinstance(props_before, QColor): target_shape.color = QColor(props_before) # Restore with copy
                                         else: valid_restore = False
                                     elif action == 'change_alpha':
                                         if isinstance(props_before, int): target_shape.alpha = props_before
                                         else: valid_restore = False
                                     elif action == 'toggle_fill':
                                         if isinstance(props_before, bool): target_shape.filled = props_before
                                         else: valid_restore = False
                                     elif action == 'change_line_style':
                                         if isinstance(props_before, Qt.PenStyle): target_shape.line_style = props_before
                                         else: valid_restore = False
                                     elif action == 'change_line_thickness':
                                         if isinstance(props_before, int): target_shape.line_thickness = props_before
                                         else: valid_restore = False
                                     elif action == 'edit_text':
                                          if isinstance(props_before, dict):
                                               # Restore both properties and geometry from the saved dict
                                               target_shape.text_properties = deepcopy(props_before.get('text_properties'))
                                               target_shape.geometry = deepcopy(props_before.get('geometry'))
                                          else: valid_restore = False; print(f"Warning: Invalid prev props for edit_text undo.")

                                     if not valid_restore: print(f"Warning: Invalid property type '{type(props_before)}' for undo action '{action}' on index {original_index}.")
                                     else: indices_restored += 1

                                except Exception as e_prop:
                                     print(f"Error restoring property for '{action}' on index {original_index}: {e_prop}")
                            else: print(f"Warning: Missing previous properties for index {original_index}.")
                        else: print(f"Warning: Index {original_index} out of bounds during undo property restoration.")
                    if indices_restored != len(original_indices): print(f"Warning: Restored properties for {indices_restored}/{len(original_indices)} shapes.")

                elif action not in ['change_board_bg', 'change_board_pen', 'change_board_text_defaults']: # Don't warn for board-only changes
                     print(f"Warning: Mismatch or missing data for undoing property change '{action}'. Indices: {len(original_indices)}, Props: {len(previous_props_map)}")

            elif action == 'clear':
                shapes_before = state_to_undo.get('all_shapes_before')
                if shapes_before is not None: self.shapes = shapes_before
                else: print("Warning: Missing 'all_shapes_before' data for undo clear.")
            elif action == 'load':
                shapes_before = state_to_undo.get('all_shapes_before')
                if shapes_before is not None: self.shapes = shapes_before
                else: print("Warning: Missing 'all_shapes_before' data for undo load.")
            elif action == 'load_join':
                 # Restore shapes *before* the join
                 shapes_before = state_to_undo.get('involved_shapes_before_action')
                 if shapes_before is not None: self.shapes = shapes_before
                 else: print("Warning: Missing 'involved_shapes_before_action' data for undo load_join.")

            self.redo_stack.append(redo_state)
            self.selected_shapes = []
            self.current_drawing_shape = None
            self.resizing = False
            self.dragging = False
            print(f"Undo successful. Redo stack size: {len(self.redo_stack)}")
            if action not in ['change_board_pen', 'change_board_text_defaults']: # Avoid full reconfigure for just pen/text default change
                self._configure_mode()
            self.update()
        except Exception as e:
            print(f"Error during undo operation for action '{action}': {e}")
            traceback.print_exc()


    def redo(self):
        if not self.redo_stack:
            print("Redo stack is empty")
            return
        state_to_redo = self.redo_stack.pop()
        action = state_to_redo['action']
        print(f"Redoing action: {action}")

        try:
            # Prepare state for next undo *before* applying redo changes
            undo_state = {
                 'action': action,
                 'involved_shapes_before_action': deepcopy(state_to_redo.get('involved_shapes_before_action')),
                 'involved_shapes_after_action': deepcopy(state_to_redo.get('involved_shapes_after_action')),
                 'previous_properties': deepcopy(state_to_redo.get('previous_properties_for_redo')), # Use the saved prev props for next undo
                 'original_indices': deepcopy(state_to_redo.get('original_indices')),
                 'all_shapes_before': deepcopy(state_to_redo.get('all_shapes_before')),
                 'paste_count': state_to_redo.get('paste_count'),
                 'board_bg_before': deepcopy(state_to_redo.get('board_bg_before')), # Carry over original 'before' color
                 'board_pen_before': deepcopy(state_to_redo.get('board_pen_before')),# Carry over original 'before' color
                 'board_text_defaults_before': deepcopy(state_to_redo.get('board_text_defaults_before')), # Carry over original 'before' defaults
            }


            # Restore the state *after* the original action (which was stored as 'before_undo')
            restored_shapes = state_to_redo.get('involved_shapes_before_undo')
            if restored_shapes is not None:
                 self.shapes = restored_shapes # Restore the entire shape list
            else:
                 print(f"Warning: 'involved_shapes_before_undo' was None during redo for action '{action}'. State might be incorrect.")


            # Handle board background/pen/text defaults separately using the stored 'before_undo' state
            if action == 'change_board_bg':
                 restored_bg_color = state_to_redo.get('board_bg_before_undo')
                 if restored_bg_color and isinstance(restored_bg_color, QColor):
                      self.board_background_color = restored_bg_color
                      print(f"Redid board background change to {self.board_background_color.name(QColor.HexArgb)}")
                      self._configure_mode() # Reconfigure needed
                 else: print(f"Warning: Invalid board bg color found during redo: {restored_bg_color}")
            elif action == 'change_board_pen':
                 restored_pen_color = state_to_redo.get('board_pen_before_undo')
                 if restored_pen_color and isinstance(restored_pen_color, QColor):
                      self.current_pen_color_board = restored_pen_color
                      self.board_color_changed.emit(restored_pen_color) # Signal change
                      print(f"Redid board pen change to {self.current_pen_color_board.name(QColor.HexArgb)}")
                 else: print(f"Warning: Invalid board pen color found during redo: {restored_pen_color}")
            elif action == 'change_board_text_defaults':
                 restored_defaults = state_to_redo.get('board_text_defaults_before_undo')
                 if restored_defaults and isinstance(restored_defaults, dict):
                      self.board_default_text_properties = restored_defaults
                      print(f"Redid board text default change to: {self.board_default_text_properties}")
                 else: print(f"Warning: Invalid board text defaults found during redo: {restored_defaults}")

            # Post-redo actions (like updating defaults after text edit redo)
            if action == 'edit_text':
                 indices = state_to_redo.get('original_indices', [])
                 if indices and 0 <= indices[0] < len(self.shapes):
                      edited_shape = self.shapes[indices[0]]
                      if edited_shape.type == 'text' and edited_shape.text_properties:
                          # Re-apply edited props as new defaults (Mode dependent)
                          if not self.board_mode:
                               self.default_text_properties = deepcopy(edited_shape.text_properties)
                               self.default_text_properties['text'] = '' # Don't save text
                               self.defaults_changed.emit()
                               print("Redo edit_text: Updated normal defaults.")
                          else:
                              # Save the state before changing BOARD defaults
                              prev_board_defaults = deepcopy(self.board_default_text_properties)
                              # Update BOARD defaults
                              self.board_default_text_properties = deepcopy(edited_shape.text_properties)
                              self.board_default_text_properties['text'] = ''
                              # Add an undo state for the default change itself
                              self.save_state('change_board_text_defaults', previous_geometries={'board_text_defaults': prev_board_defaults})
                              print("Redo edit_text: Updated BOARD text defaults.")
                 else: print("Warning: Could not find edited text shape on redo.")


            self.undo_stack.append(undo_state) # Add the prepared state to undo stack
            self.selected_shapes = []
            self.current_drawing_shape = None
            self.resizing = False
            self.dragging = False
            print(f"Redo successful. Undo stack size: {len(self.undo_stack)}")
            # Reconfigure needed if board background changed or shapes modified significantly
            if action not in ['change_board_pen', 'change_board_text_defaults']:
                 self._configure_mode()
            self.update()
        except Exception as e:
            print(f"Error during redo operation for action '{action}': {e}")
            traceback.print_exc()


    def mousePressEvent(self, event: QMouseEvent):
        if not self.drawing_mode: return

        # Ensure window has focus when drawing starts
        if not self.isActiveWindow():
            self.activateWindow()
        if not self.hasFocus():
            self.setFocus(Qt.MouseFocusReason)

        pos = event.position()

        if event.button() == Qt.LeftButton:
            modifiers = event.modifiers()
            ctrl_pressed = modifiers & Qt.ControlModifier
            alt_pressed = modifiers & Qt.AltModifier
            shift_pressed = modifiers & Qt.ShiftModifier

            handle = self.get_handle_at(pos)
            if handle: # Start Resizing
                shape, handle_name = handle
                print(f"Starting resize on shape {shape.type}, handle: {handle_name}")
                self.resizing = True
                self.resize_handle = handle_name
                self.drag_start_pos = pos
                self.selected_shapes = [shape] # Select only the shape being resized
                self.drag_start_geometries = {}
                current_indices_for_resize = []
                try:
                    idx = self.shapes.index(shape)
                    self.drag_start_geometries[idx] = deepcopy(shape.geometry)
                    current_indices_for_resize.append(idx)
                except ValueError: pass # Shape not found
                self.undo_indices_cache = current_indices_for_resize
                self.update()
                return

            top_shape = None
            top_shape_idx = -1
            for i, shape in enumerate(reversed(self.shapes)):
                if shape and shape.geometry and shape.contains(pos):
                    top_shape = shape
                    top_shape_idx = len(self.shapes) - 1 - i
                    break

            if top_shape: # Clicked on existing shape
                original_props = {}
                action = None
                key_held = self.pressed_keys

                # --- Quick Property Actions (Apply NORMAL mode settings) ---
                if not self.board_mode and top_shape_idx != -1:
                    if ctrl_pressed and alt_pressed and shift_pressed:
                        action = 'change_alpha'; original_props[top_shape_idx] = top_shape.alpha; top_shape.alpha = self.current_alpha
                    elif ctrl_pressed and alt_pressed:
                        action = 'change_color'; original_props[top_shape_idx] = deepcopy(top_shape.color); top_shape.color = self.current_pen_color
                    elif Qt.Key_F in key_held:
                        action = 'toggle_fill'; original_props[top_shape_idx] = top_shape.filled; top_shape.filled = not top_shape.filled

                    if action:
                        print(f"Performing quick action '{action}' on shape {top_shape_idx}")
                        self.save_state(action, shapes_involved=[top_shape], previous_geometries=original_props, indices=[top_shape_idx])
                        self.update()
                        # Also update control panel color if needed
                        if action == 'change_color' and self.control_panel:
                            self.control_panel.update_draw_color_button_style(self.current_pen_color)
                        return
                # --- End Quick Property Actions ---

                if ctrl_pressed: # Add/Remove from selection
                    if top_shape in self.selected_shapes: self.selected_shapes.remove(top_shape)
                    else: self.selected_shapes.append(top_shape)
                    print(f"Selection changed: {len(self.selected_shapes)} shapes selected.")
                    self.update()
                    return
                else: # Normal click (start drag or select)
                    if top_shape not in self.selected_shapes:
                        self.selected_shapes = [top_shape]
                        print(f"Selecting shape {top_shape_idx}")
                    print(f"Starting drag for {len(self.selected_shapes)} selected shape(s)")
                    self.dragging = True
                    self.drag_start_pos = pos
                    self.drag_start_geometries = {}
                    current_indices_for_drag = []
                    for s in self.selected_shapes:
                         try:
                              idx = self.shapes.index(s)
                              self.drag_start_geometries[idx] = deepcopy(s.geometry)
                              current_indices_for_drag.append(idx)
                         except ValueError: pass
                    self.undo_indices_cache = current_indices_for_drag
                    self.update()
                    return

            else: # Click on Empty Space (Start Drawing)
                self.selected_shapes = [] # Clear selection when starting to draw
                self.dragging = False
                self.resizing = False
                self.drag_start_pos = pos

                # --- Determine properties based on mode ---
                use_board_props = self.board_mode
                pen_color = self.current_pen_color_board if use_board_props else self.current_pen_color
                # Use common alpha/thickness/style settings
                alpha = self.current_alpha
                thickness = self.current_line_thickness
                line_style = self.current_line_style
                arrow_size = self.current_arrow_head_size
                brush_size = self.brush_size
                # Fill depends on control panel setting
                filled = self.control_panel.fill_check.isChecked() if self.control_panel else True


                if self.current_tool in ['rect', 'ellipse']:
                    geom = QRectF(pos, QSizeF(0, 0))
                    self.current_drawing_shape = Shape(self.current_tool, geom, pen_color, filled=filled, alpha=alpha, line_thickness=thickness, line_style=line_style )
                elif self.current_tool == 'text':
                    self.current_drawing_shape = None # No preview while dragging for text
                elif self.current_tool in ['line', 'arrow']:
                    self.current_drawing_shape = Shape(self.current_tool, [pos, pos], pen_color, filled=False, alpha=alpha, line_thickness=thickness, line_style=line_style, arrow_head_size=(arrow_size if self.current_tool == 'arrow' else None) )
                elif self.current_tool == 'triangle':
                     # Initial triangle preview can be just a line
                     self.current_drawing_shape = Shape('triangle', [pos, pos, pos], pen_color, filled=filled, alpha=alpha, line_thickness=thickness, line_style=line_style )
                elif self.current_tool in ['polygon', 'line_point']:
                    if not self.polygon_points: # Start new
                        print(f"Starting new {self.current_tool}")
                        self.polygon_points = [pos]
                    else: # Add point or finish
                        if self.current_tool == 'polygon' and len(self.polygon_points) >= 2: # Need >=2 points to check distance to first
                            dist_sq = QPointF.dotProduct(pos - self.polygon_points[0], pos - self.polygon_points[0])
                            # Close if near first point (and have enough points for polygon)
                            if dist_sq < (self.handle_size * 1.5)**2 and len(self.polygon_points) >= 3 :
                                print("Closing polygon by clicking near start point.")
                                self.finish_drawing_poly_line()
                                return
                        print(f"Adding point to {self.current_tool}")
                        self.polygon_points.append(pos)
                    self.update()
                    return # Don't create preview shape on point add
                elif self.current_tool == 'brush':
                    self.brush_points = [pos]
                    # Use brush_size for thickness
                    self.current_drawing_shape = Shape('brush', self.brush_points, pen_color, filled=False, alpha=alpha, line_thickness=brush_size, line_style=Qt.SolidLine )
                self.update()

        elif event.button() == Qt.RightButton and self.drawing_mode:
            if self.current_tool in ['polygon', 'line_point'] and self.polygon_points:
                self.finish_drawing_poly_line() # Finish on RMB
            else:
                print("Right-click: Clearing selection/drawing action.")
                self.selected_shapes = []
                self.current_drawing_shape = None
                self.polygon_points = []
                self.brush_points = []
                self.resizing = False
                self.dragging = False
                self.update()

    def finish_drawing_poly_line(self):
        """Helper function to finalize the current polygon or line_point drawing."""
        tool = self.current_tool
        min_points = 3 if tool == 'polygon' else 2 # Min points needed
        # Add a check for polygon to avoid self-intersection by double-clicking last point
        if tool == 'polygon' and len(self.polygon_points) >= 2 and self.polygon_points[-1] == self.polygon_points[-2]:
            print("Ignoring redundant last point in polygon.")
            self.polygon_points.pop() # Remove the duplicate last point


        if len(self.polygon_points) >= min_points:
            print(f"Finalizing {tool} shape.")
            # Determine properties based on mode
            use_board_props = self.board_mode
            pen_color = self.current_pen_color_board if use_board_props else self.current_pen_color
            alpha = self.current_alpha
            thickness = self.current_line_thickness
            line_style = self.current_line_style
            # Fill only applies to polygon and depends on checkbox
            filled = (tool == 'polygon') and (self.control_panel.fill_check.isChecked() if self.control_panel else True)

            # Use a copy of polygon_points for the shape
            final_geometry = self.polygon_points[:]
            final_shape = Shape(tool, final_geometry, pen_color, filled=filled, alpha=alpha, line_thickness=thickness, line_style=line_style)
            self.shapes.append(final_shape)
            self.save_state('draw', shapes_involved=[final_shape], indices=[len(self.shapes)-1])
            self._configure_mode()
            print(f"{tool.capitalize()} shape added.")

            # --- Auto-exit drawing mode ---
            if not self.board_mode:
                 print("Auto-exiting drawing mode after poly/line.")
                 self.set_drawing_mode(False)
            # --- End Auto-exit ---

        else:
            print(f"Not enough points ({len(self.polygon_points)}/{min_points}) to create {tool}, discarding.")
        # Reset state regardless of success
        self.polygon_points = []
        self.current_drawing_shape = None # Ensure no dangling preview
        self.update()


    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.drawing_mode: return

        pos = event.position()
        modifiers = event.modifiers()
        shift_pressed = modifiers & Qt.ShiftModifier

        # --- Handle Resizing ---
        if self.resizing and self.resize_handle and self.drag_start_pos and self.selected_shapes:
            if not self.selected_shapes: return
            shape_being_resized = self.selected_shapes[0]
            shape_index = -1
            try: shape_index = self.shapes.index(shape_being_resized)
            except ValueError: print("Warning: Resized shape not found in list."); return

            if shape_index != -1 and shape_index in self.drag_start_geometries:
                original_geo = self.drag_start_geometries[shape_index]
                center = QPointF()

                # Recalculate center based on *current* geometry before transform
                current_geo_for_center = shape_being_resized.geometry
                if isinstance(current_geo_for_center, QRectF) and current_geo_for_center.isValid():
                    center = current_geo_for_center.center()
                elif isinstance(current_geo_for_center, list):
                     valid_points = [p for p in current_geo_for_center if isinstance(p, QPointF)]
                     if valid_points: center = QPointF(sum(p.x() for p in valid_points)/len(valid_points), sum(p.y() for p in valid_points)/len(valid_points))
                can_rotate = not center.isNull() # Can we apply rotation?

                # Calculate inverse transform based on current center and rotation
                inv_transform = QTransform()
                if shape_being_resized.rotation != 0 and can_rotate:
                    inv_transform.translate(center.x(), center.y())
                    inv_transform.rotate(-shape_being_resized.rotation)
                    inv_transform.translate(-center.x(), -center.y())
                unrotated_pos = inv_transform.map(pos) if can_rotate else pos # Target position in unrotated space

                # Calculate unrotated version of the *original* geometry for aspect ratio etc.
                unrotated_original_geo = original_geo
                if shape_being_resized.rotation != 0 and can_rotate:
                    if isinstance(original_geo, QRectF):
                         unrotated_original_geo = inv_transform.mapRect(original_geo)
                    elif isinstance(original_geo, list):
                         # Ensure we only transform valid points
                         valid_original_points = [p for p in original_geo if isinstance(p, QPointF)]
                         if len(valid_original_points) == len(original_geo):
                              unrotated_original_geo = [inv_transform.map(p) for p in valid_original_points]
                         else:
                              print("Warning: Cannot unrotate original list geometry due to invalid points.")
                              unrotated_original_geo = None # Flag as invalid


                if isinstance(original_geo, QRectF) and isinstance(unrotated_original_geo, QRectF):
                    new_unrotated_rect = QRectF(unrotated_original_geo) # Start with unrotated original
                    # Apply changes in unrotated space based on handle
                    if self.resize_handle == 'top_left': new_unrotated_rect.setTopLeft(unrotated_pos)
                    elif self.resize_handle == 'top_right': new_unrotated_rect.setTopRight(unrotated_pos)
                    elif self.resize_handle == 'bottom_right': new_unrotated_rect.setBottomRight(unrotated_pos)
                    elif self.resize_handle == 'bottom_left': new_unrotated_rect.setBottomLeft(unrotated_pos)

                    new_unrotated_rect = new_unrotated_rect.normalized()

                    # Maintain aspect ratio if shift is pressed
                    if shift_pressed and unrotated_original_geo.height() > 1e-6:
                        original_aspect = unrotated_original_geo.width() / unrotated_original_geo.height()
                        current_width = new_unrotated_rect.width()
                        current_height = new_unrotated_rect.height()
                        if current_height < 1e-6: current_height = 1e-6 # Avoid division by zero

                        new_width = current_width
                        new_height = current_height

                        # Adjust the non-dominant dimension based on the aspect ratio
                        if 'left' in self.resize_handle or 'right' in self.resize_handle: # Width is driving
                            new_height = current_width / original_aspect
                        else: # Height is driving (or corner)
                            new_width = current_height * original_aspect

                        # Reposition the rectangle based on the fixed corner and new size
                        if self.resize_handle == 'top_left':
                            new_unrotated_rect = QRectF(new_unrotated_rect.right() - new_width, new_unrotated_rect.bottom() - new_height, new_width, new_height)
                        elif self.resize_handle == 'top_right':
                            new_unrotated_rect = QRectF(new_unrotated_rect.left(), new_unrotated_rect.bottom() - new_height, new_width, new_height)
                        elif self.resize_handle == 'bottom_right':
                            new_unrotated_rect = QRectF(new_unrotated_rect.left(), new_unrotated_rect.top(), new_width, new_height)
                        elif self.resize_handle == 'bottom_left':
                            new_unrotated_rect = QRectF(new_unrotated_rect.right() - new_width, new_unrotated_rect.top(), new_width, new_height)


                    # Apply rotation back to the final unrotated rectangle
                    final_new_geo = new_unrotated_rect.normalized()
                    if shape_being_resized.rotation != 0 and can_rotate:
                         fwd_transform = QTransform()
                         fwd_transform.translate(center.x(), center.y())
                         fwd_transform.rotate(shape_being_resized.rotation)
                         fwd_transform.translate(-center.x(), -center.y())
                         final_new_geo = fwd_transform.mapRect(final_new_geo)

                    shape_being_resized.geometry = final_new_geo

                elif isinstance(original_geo, list) and 'vertex_' in self.resize_handle:
                     # Handle vertex move for polygons, lines etc.
                    try:
                        vertex_idx = int(self.resize_handle.split('_')[1])
                        if 0 <= vertex_idx < len(shape_being_resized.geometry):
                             current_points = shape_being_resized.geometry # This is the potentially rotated list

                             # Create forward transform to rotate the new vertex position back
                             fwd_transform = QTransform()
                             if shape_being_resized.rotation != 0 and can_rotate:
                                 fwd_transform.translate(center.x(), center.y())
                                 fwd_transform.rotate(shape_being_resized.rotation)
                                 fwd_transform.translate(-center.x(), -center.y())

                             # Apply forward transform to the unrotated target position
                             rotated_new_pos = fwd_transform.map(unrotated_pos) if can_rotate else unrotated_pos

                             # Update the point in the list
                             if isinstance(current_points, list):
                                  current_points[vertex_idx] = rotated_new_pos
                             else: print("Warning: geometry is not a list during vertex resize.")

                    except (ValueError, IndexError) as e: print(f"Error parsing resize handle vertex index: {self.resize_handle} - {e}")

                self.update() # Update visuals during resize
            return

        # --- Handle Dragging ---
        if self.dragging and self.selected_shapes and self.drag_start_pos:
            delta = pos - self.drag_start_pos
            moved = False
            for shape in self.selected_shapes:
                shape_index = -1
                try: shape_index = self.shapes.index(shape)
                except ValueError: continue # Skip if shape not found

                if shape_index != -1 and shape_index in self.drag_start_geometries:
                    original_geo = self.drag_start_geometries[shape_index]
                    if isinstance(original_geo, QRectF) and original_geo.isValid():
                         shape.geometry = original_geo.translated(delta)
                         moved = True
                    elif isinstance(original_geo, list):
                         valid_original_points = [p for p in original_geo if isinstance(p, QPointF)]
                         if len(valid_original_points) == len(original_geo):
                            # Create a new list with translated points
                            shape.geometry = [p + delta for p in valid_original_points]
                            moved = True
                         else: print("Warning: Original geometry list contained non-QPointF during drag.")

            if moved: self.update()
            return

        # --- Handle Drawing Preview ---
        if self.current_drawing_shape and self.drag_start_pos:
            tool = self.current_drawing_shape.type
            start_pos = self.drag_start_pos

            if tool in ['rect', 'ellipse']:
                new_rect = QRectF(start_pos, pos).normalized()
                if shift_pressed:
                    size = max(new_rect.width(), new_rect.height())
                    dx = pos.x() - start_pos.x(); dy = pos.y() - start_pos.y()
                    new_top_left = QPointF(start_pos)
                    # Adjust top-left based on drag direction for square/circle
                    if dx < 0: new_top_left.setX(start_pos.x() - size)
                    if dy < 0: new_top_left.setY(start_pos.y() - size)
                    new_rect = QRectF(new_top_left, QSizeF(size, size))
                self.current_drawing_shape.geometry = new_rect
            elif tool in ['line', 'arrow']:
                end_pos = pos
                if shift_pressed:
                    dx = pos.x() - start_pos.x(); dy = pos.y() - start_pos.y()
                    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                        angle_rad = math.atan2(dy, dx)
                        snapped_deg = round(math.degrees(angle_rad) / 45.0) * 45.0
                        snapped_rad = math.radians(snapped_deg)
                        length = math.sqrt(dx**2 + dy**2)
                        end_pos = start_pos + QPointF(length * math.cos(snapped_rad), length * math.sin(snapped_rad))
                self.current_drawing_shape.geometry = [start_pos, end_pos]
            elif tool == 'triangle':
                 # Make triangle based on bounding box of drag
                 rect = QRectF(start_pos, pos).normalized()
                 p1 = rect.bottomLeft()
                 p2 = rect.bottomRight()
                 p3 = QPointF(rect.center().x(), rect.top())
                 self.current_drawing_shape.geometry = [p1, p2, p3]
            elif tool == 'brush' and self.brush_points:
                 # Add point only if moved significantly
                 if QPointF.dotProduct(pos - self.brush_points[-1], pos - self.brush_points[-1]) > 4: # Threshold squared
                      self.brush_points.append(pos)
                      self.current_drawing_shape.geometry = self.brush_points[:] # Update geometry with copy
            if tool not in ['text', 'polygon', 'line_point']:
                self.update()

        # --- Update Polygon/LinePoint Preview Line ---
        elif self.current_tool in ['polygon', 'line_point'] and self.polygon_points:
            self.update()


    def mouseReleaseEvent(self, event: QMouseEvent):
        if not self.drawing_mode: return

        pos = event.position()
        if event.button() == Qt.LeftButton:
            # --- Finalize Resizing ---
            if self.resizing:
                print(f"Finished resizing shape, handle: {self.resize_handle}")
                if self.selected_shapes:
                    shape_resized = self.selected_shapes[0]
                    shape_index = -1
                    if hasattr(self, 'undo_indices_cache') and self.undo_indices_cache:
                         shape_index = self.undo_indices_cache[0]

                    if shape_index != -1 and shape_index in self.drag_start_geometries:
                        original_geo = self.drag_start_geometries[shape_index]
                        final_geo = shape_resized.geometry
                        geo_changed = False
                        # Check for significant change before saving undo state
                        # Use a small tolerance for float comparisons
                        tolerance = 0.5
                        if isinstance(final_geo, QRectF) and isinstance(original_geo, QRectF):
                             if abs(final_geo.x() - original_geo.x()) > tolerance or \
                                abs(final_geo.y() - original_geo.y()) > tolerance or \
                                abs(final_geo.width() - original_geo.width()) > tolerance or \
                                abs(final_geo.height() - original_geo.height()) > tolerance:
                                 geo_changed = True
                        elif isinstance(final_geo, list) and isinstance(original_geo, list):
                             if len(final_geo) != len(original_geo): geo_changed = True
                             else:
                                 for i in range(len(final_geo)):
                                      if not isinstance(final_geo[i], QPointF) or not isinstance(original_geo[i], QPointF): geo_changed = True; break
                                      delta = final_geo[i] - original_geo[i]
                                      if QPointF.dotProduct(delta, delta) > tolerance**2: geo_changed = True; break # Check squared distance
                        elif final_geo != original_geo: # Fallback for other types or if one is None
                             geo_changed = True

                        if geo_changed:
                             print("Resize resulted in geometry change, saving state.")
                             self.save_state('resize', shapes_involved=[shape_resized], previous_geometries={shape_index: original_geo}, indices=[shape_index])
                        else: print("Resize resulted in negligible geometry change, not saving undo.")
                    else: print("Warning: Could not determine shape or original geometry for resize undo.")
                else: print("Warning: No shape selected or index invalid at end of resize.")
                # Reset resize state
                self.resizing = False; self.resize_handle = None; self.drag_start_pos = None; self.drag_start_geometries = {}; self.undo_indices_cache = []
                self._configure_mode(); self.update()
                return # Resizing finished

            # --- Finalize Dragging ---
            if self.dragging:
                moved_shapes_indices = []
                prev_geos = {}
                moved_significantly = False
                if self.selected_shapes and self.drag_start_pos:
                     delta = pos - self.drag_start_pos
                     if delta.manhattanLength() > 2 and hasattr(self, 'undo_indices_cache'): # Only save if moved noticeably
                          moved_significantly = True
                          for shape_index in self.undo_indices_cache:
                               if 0 <= shape_index < len(self.shapes) and shape_index in self.drag_start_geometries:
                                    moved_shape = self.shapes[shape_index]
                                    moved_shapes_indices.append(shape_index)
                                    prev_geos[shape_index] = self.drag_start_geometries[shape_index]
                          if moved_shapes_indices:
                               shapes_involved_in_move = [self.shapes[i] for i in moved_shapes_indices if 0 <= i < len(self.shapes)]
                               print("Drag ended, saving move state.")
                               self.save_state('move', shapes_involved=shapes_involved_in_move, previous_geometries=prev_geos, indices=moved_shapes_indices)
                          else: print("Drag ended, but couldn't map indices/geometries for undo.")
                     else: print(f"Drag ended, distance too small ({delta.manhattanLength()}) or indices missing, not saving undo state.")
                # Reset drag state
                self.dragging = False; self.drag_start_pos = None; self.drag_start_geometries = {}; self.undo_indices_cache = []
                self.update() # Update visuals even if not saved for undo
                return # Dragging finished

            # --- Finalize Drawing (Excluding Text, Polygon, LinePoint) ---
            if self.current_drawing_shape and self.current_tool not in ['text', 'polygon', 'line_point']:
                tool = self.current_drawing_shape.type
                valid_final_shape = True
                final_shape_for_undo = None
                geo = self.current_drawing_shape.geometry

                # Check validity based on size
                min_size = 3 # Minimum pixels for width/height or length
                if tool in ['rect', 'ellipse']:
                    if not isinstance(geo, QRectF) or not geo.isValid() or geo.width() < min_size or geo.height() < min_size: valid_final_shape = False
                elif tool in ['line', 'arrow', 'triangle']:
                     if isinstance(geo, list) and len(geo) >= 2:
                          p_start = geo[0]; p_end = geo[-1]
                          if isinstance(p_start, QPointF) and isinstance(p_end, QPointF):
                              if (p_end - p_start).manhattanLength() < min_size: valid_final_shape = False
                          else: valid_final_shape = False # Invalid points
                     else: valid_final_shape = False # Not enough points
                elif tool == 'brush':
                    if not isinstance(geo, list) or len(geo) < 2: valid_final_shape = False # Need at least 2 points for brush

                if valid_final_shape:
                    print(f"Adding finalized {tool} shape.")
                    # Use the current_drawing_shape directly, it holds the final state
                    final_shape_for_undo = self.current_drawing_shape
                    self.shapes.append(self.current_drawing_shape)
                    self.save_state('draw', shapes_involved=[final_shape_for_undo], indices=[len(self.shapes)-1])
                    self._configure_mode()

                    # --- Auto-exit drawing mode ---
                    if not self.board_mode:
                         print("Auto-exiting drawing mode after shape.")
                         self.set_drawing_mode(False)
                    # --- End Auto-exit ---

                else: print(f"Discarding tiny/invalid {tool} shape.")

                # Reset drawing state
                self.current_drawing_shape = None
                self.brush_points = []
                self.drag_start_pos = None
                self.update()
                return # Drawing finished

            # --- Handle Text Tool Release ---
            if self.current_tool == 'text' and self.drag_start_pos:
                print(f"Text tool released at {pos}, origin {self.drag_start_pos}")
                # Determine which defaults to use based on mode
                initial_props_for_dialog = deepcopy(self.board_default_text_properties if self.board_mode else self.default_text_properties)
                initial_props_for_dialog['text'] = '' # Start empty
                # Use appropriate color based on mode
                pen_color = self.current_pen_color_board if self.board_mode else self.current_pen_color
                initial_props_for_dialog['color'] = pen_color.name(QColor.HexRgb) # Use HexRGB for color picker default

                # Calculate initial rect based on drag (if any)
                initial_rect = QRectF(self.drag_start_pos, pos).normalized()
                if initial_rect.width() < 10 or initial_rect.height() < 10:
                     # If just clicked, use start pos and pass None for rect
                     initial_rect = None
                     origin_pos = self.drag_start_pos
                else:
                     origin_pos = initial_rect.topLeft() # Use top-left of drag rect

                self.show_text_dialog(origin_pos, shape_to_edit=None, initial_props=initial_props_for_dialog, initial_rect=initial_rect)
                # Reset state
                self.drag_start_pos = None
                self.current_drawing_shape = None
                self.update()
                # Note: show_text_dialog handles auto-exit if successful
                return # Text handling finished

            # --- Handle Polygon/LinePoint Point Click ---
            if self.current_tool in ['polygon', 'line_point']:
                # Point addition is handled in mousePress, update happens there
                self.update()
                return

        elif event.button() == Qt.RightButton and self.drawing_mode:
             # RMB finalization handled in press/double-click
             pass


    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if not self.drawing_mode: return

        pos = event.position()
        if event.button() == Qt.LeftButton:
            # --- Finish Polygon/LinePoint on Double-Click ---
            if self.current_tool in ['polygon', 'line_point'] and self.polygon_points:
                self.finish_drawing_poly_line() # Finish on DblClk
                return

            # --- Edit Text or Delete Shape ---
            top_shape = None
            top_shape_idx = -1
            for i, shape in enumerate(reversed(self.shapes)):
                if shape and shape.geometry and shape.contains(pos):
                    top_shape = shape
                    top_shape_idx = len(self.shapes) - 1 - i
                    break

            if top_shape:
                if top_shape.type == 'text':
                    print(f"Editing text shape {top_shape_idx} properties (DblClk)")
                    # Pass the current text properties for the dialog
                    current_props = deepcopy(top_shape.text_properties) if top_shape.text_properties else \
                                    deepcopy(self.board_default_text_properties if self.board_mode else self.default_text_properties)
                    self.show_text_dialog(pos, shape_to_edit=top_shape, initial_props=current_props) # Pass current props
                    return
                else:
                    # Delete Non-Text Shape on Double-Click
                    print(f"Deleting shape {top_shape_idx} via double-click")
                    try:
                        shape_copy = deepcopy(top_shape)
                        original_index = self.shapes.index(top_shape)
                        self.shapes.pop(original_index)
                        # Remove from selection if present
                        if top_shape in self.selected_shapes:
                            self.selected_shapes.remove(top_shape)
                        self.save_state('delete', shapes_involved=[shape_copy], indices=[original_index])
                        self._configure_mode(); self.update()
                    except ValueError: print(f"Error: Shape to delete not found in list.")
                    except Exception as e: print(f"Error during shape deletion: {e}"); traceback.print_exc()
                    return

            # If no shape found, double-click on empty space does nothing extra
            self.update()


    def keyPressEvent(self, event: QKeyEvent):
        # This handles keys ONLY when the overlay window has focus.
        # Global hotkeys (Alt+F1/F2/F3) are handled by nativeEvent.
        if not self.drawing_mode: # Only process keys if drawing mode is active
             super().keyPressEvent(event) # Pass to parent if not handled
             return

        key = event.key()
        modifiers = event.modifiers()
        ctrl_pressed = modifiers & Qt.ControlModifier
        alt_pressed = modifiers & Qt.AltModifier
        shift_pressed = modifiers & Qt.ShiftModifier
        keypad_modifier = modifiers & Qt.KeypadModifier # Check for keypad modifier

        self.pressed_keys.add(key)
        print(f"KeyPress (Overlay Focus): Key={key} ({hex(key)}), Modifiers={modifiers}, Keypad={keypad_modifier}, Drawing={self.drawing_mode}")


        # --- Handle keys that require focus ---
        if key == Qt.Key_Escape:
            print("Escape pressed (overlay focus)")
            current_time = time.time()
            double_press_interval = 0.4

            if self.board_mode and (current_time - self.last_esc_press_time < double_press_interval):
                print("Double Escape detected: Attempting to exit BOARD/EDIT mode.")
                self.exit_board_mode(ask_save=False) # Auto-save now
                self.last_esc_press_time = 0
                event.accept(); return # Consume event
            self.last_esc_press_time = current_time

            # Handle cancellations within drawing mode
            if self.current_tool in ['polygon', 'line_point'] and self.polygon_points:
                 print("Cancelling polygon/line_point drawing."); self.polygon_points = []; self.current_drawing_shape = None; self.update(); event.accept(); return
            elif self.current_drawing_shape:
                 print("Cancelling current shape drawing preview."); self.current_drawing_shape = None; self.brush_points = []; self.update(); event.accept(); return
            elif self.resizing or self.dragging:
                 print("Cancelling resize/drag.")
                 if self.drag_start_geometries:
                      # Restore geometry for cancelled resize/drag
                      for index, original_geo in self.drag_start_geometries.items():
                           if 0 <= index < len(self.shapes): self.shapes[index].geometry = original_geo
                 self.resizing = False; self.dragging = False; self.resize_handle = None; self.drag_start_pos = None; self.drag_start_geometries = {}; self.undo_indices_cache = []
                 self.update(); event.accept(); return
            elif self.board_mode:
                 print("Single Esc in Board/Edit mode - press again quickly to exit.")
                 event.accept(); return # Don't exit drawing on single Esc in board/edit
            else: # Normal drawing mode
                 print("Exiting drawing mode via Escape.")
                 self.set_drawing_mode(False); event.accept(); return

        # --- Alt+F1/F2/F3 are handled by nativeEvent ---

        # --- Numpad Period/Comma/Delete for Color Picker ---
        # Qt.Key_Period (46) or Qt.Key_Delete (0x01000007) - some keyboards map Numpad Del differently
        # Let's check for period (decimal point) with KeypadModifier OR Delete key with KeypadModifier
        is_numpad_del_or_period = (key == Qt.Key_Period or key == Qt.Key_Delete) and keypad_modifier
        print(f"Checking Numpad Del/Period: Key={key}, KeypadMod={keypad_modifier}, Result={is_numpad_del_or_period}") # Debug

        if is_numpad_del_or_period:
            if self.selected_shapes:
                print(f"Numpad '.' or 'Del' detected with selected shapes.")
                is_board_or_edit = self.drawing_mode and self.board_mode
                initial_color = self.selected_shapes[0].color # Use first selected shape's color as initial

                options = QColorDialog.ColorDialogOption.DontUseNativeDialog
                # Allow alpha editing only if in normal draw mode
                if not is_board_or_edit:
                    options |= QColorDialog.ColorDialogOption.ShowAlphaChannel
                    dialog_title = "Choose Draw Color for Selection"
                else:
                    dialog_title = "Choose Edit/Board Color for Selection"


                color = QColorDialog.getColor(initial_color, self, dialog_title, options)

                if color.isValid():
                    print(f"Applying color {color.name(QColor.HexArgb)} to {len(self.selected_shapes)} selected shapes.")
                    prev_props = {}
                    current_indices = []
                    changed_shapes = []
                    for shape in self.selected_shapes:
                        try:
                            shape_idx = self.shapes.index(shape)
                            current_indices.append(shape_idx)
                            prev_props[shape_idx] = deepcopy(shape.color)
                            # Preserve original alpha unless in Draw mode where dialog might change it
                            new_shape_color = QColor(color)
                            if is_board_or_edit:
                                new_shape_color.setAlpha(shape.color.alpha()) # Keep original alpha in Board/Edit
                            shape.color = new_shape_color
                            changed_shapes.append(shape)
                        except ValueError:
                            continue # Shape not found

                    if changed_shapes:
                        self.save_state('change_color', shapes_involved=changed_shapes, previous_geometries=prev_props, indices=current_indices)
                        self.update()
                event.accept()
                return
            else:
                print("Numpad '.' or 'Del' pressed, but no shapes selected.")


        # --- Copy/Paste (require focus) ---
        if ctrl_pressed and not shift_pressed and not alt_pressed:
             if key == Qt.Key_C: self.copy_shapes(); event.accept(); return
             elif key == Qt.Key_V: self.paste_shapes(); event.accept(); return

        # --- Undo/Redo (require focus) ---
        if key == Qt.Key_Z and ctrl_pressed:
            if shift_pressed: self.redo()
            else: self.undo()
            event.accept(); return
        elif key == Qt.Key_Y and ctrl_pressed: self.redo(); event.accept(); return

        # --- Control Panel / Shortcuts Window Toggles ---
        if key == Qt.Key_K and ctrl_pressed:
            if self.control_panel: self.control_panel.toggle_shortcuts_window(force_reset=False) # Don't force reset
            event.accept(); return
        if key == Qt.Key_Home and ctrl_pressed:
            if self.control_panel: self.control_panel.setVisible(not self.control_panel.isVisible())
            event.accept(); return

        # --- Drawing Mode Specific Keys ---
        tool_changed = False
        previous_tool = self.current_tool

        # --- BOARD/EDIT Mode Specific Shortcuts ---
        if self.board_mode:
            # BOARD: Background Transparency (Ctrl+Num 0-9)
            if ctrl_pressed and not alt_pressed and not shift_pressed and Qt.Key_0 <= key <= Qt.Key_9:
                num_value = key - Qt.Key_0
                # Map 0 -> 1 (min alpha), 9 -> 255 (opaque)
                alpha = int(round((num_value / 9.0) * 254)) + 1 if num_value > 0 else 1
                alpha = min(255, max(1, alpha)) # Clamp to [1, 255]

                current_bg = self.board_background_color
                prev_bg_color = deepcopy(current_bg)
                new_color = QColor(current_bg.red(), current_bg.green(), current_bg.blue(), alpha)
                if new_color != prev_bg_color:
                     print(f"Changing BOARD background transparency to {alpha}/255 (Key {num_value})")
                     self.save_state('change_board_bg', previous_geometries={'board_bg': prev_bg_color})
                     self.board_background_color = new_color
                     self._configure_mode(); self.update()
                else: print(f"BOARD background alpha already {alpha}, no change.")
                event.accept(); return

            # BOARD: Background Color (Alt+Num 0-9)
            elif alt_pressed and not ctrl_pressed and not shift_pressed and key in self.board_color_shortcuts:
                target_rgb_color = self.board_color_shortcuts[key]
                current_bg = self.board_background_color
                new_color = QColor(target_rgb_color.red(), target_rgb_color.green(), target_rgb_color.blue(), current_bg.alpha())
                prev_bg_color = deepcopy(current_bg)
                print(f"BOARD BG Change attempt (Alt+Num): TargetRGB={target_rgb_color.name()}, Current={prev_bg_color.name(QColor.HexArgb)}, New={new_color.name(QColor.HexArgb)}")
                if new_color != prev_bg_color:
                    print(f"Changing BOARD background color (RGB) to: {target_rgb_color.name()}, Alpha={new_color.alpha()}")
                    self.save_state('change_board_bg', previous_geometries={'board_bg': prev_bg_color})
                    self.board_background_color = new_color
                    self._configure_mode(); self.update()
                else: print("BOARD background color already set, no change.")
                event.accept(); return

            # BOARD: Pen/Shape Color (Num 0-9, no modifiers)
            elif not ctrl_pressed and not alt_pressed and not shift_pressed and key in self.board_color_shortcuts:
                target_color = self.board_color_shortcuts[key]
                if self.selected_shapes:
                    print(f"BOARD: Applying color shortcut {key} to selected: {target_color.name()}")
                    prev_props = {}; current_indices = []; changed_shapes = []
                    for shape in self.selected_shapes:
                        try: shape_idx = self.shapes.index(shape)
                        except ValueError: continue
                        if shape.color != target_color:
                             current_indices.append(shape_idx); prev_props[shape_idx] = deepcopy(shape.color)
                             shape.color = QColor(target_color); changed_shapes.append(shape)
                    if changed_shapes: self.save_state('change_color', shapes_involved=changed_shapes, previous_geometries=prev_props, indices=current_indices); self.update()
                    else: print("Selected shapes already have target color.")
                else: # Apply to current board pen
                    print(f"BOARD: Applying color shortcut {key} to current pen: {target_color.name()}")
                    prev_pen_color = deepcopy(self.current_pen_color_board)
                    if target_color != prev_pen_color:
                         self.save_state('change_board_pen', previous_geometries={'board_pen': prev_pen_color})
                         self.set_board_pen_color(QColor(target_color)) # Updates indicator via update() and signals panel
                    else: print("Board pen already has target color.")
                event.accept(); return
        # --- END BOARD/EDIT Mode Specific Shortcuts ---

        # --- NORMAL Mode Color Shortcuts ---
        elif not self.board_mode and not ctrl_pressed and not alt_pressed and not shift_pressed and key in self.color_shortcuts:
            target_color = self.color_shortcuts[key]
            if self.selected_shapes:
                print(f"NORMAL: Applying color shortcut {key} to selected: {target_color.name()}")
                prev_props = {}; current_indices = []; changed_shapes = []
                for shape in self.selected_shapes:
                    try: shape_idx = self.shapes.index(shape)
                    except ValueError: continue
                    if shape.color != target_color:
                        current_indices.append(shape_idx); prev_props[shape_idx] = deepcopy(shape.color)
                        shape.color = QColor(target_color); changed_shapes.append(shape)
                if changed_shapes: self.save_state('change_color', shapes_involved=changed_shapes, previous_geometries=prev_props, indices=current_indices); self.update()
                else: print("Selected shapes already have target color.")
            else:
                print(f"NORMAL: Applying color shortcut {key} to current pen: {target_color.name()}")
                self.set_pen_color(QColor(target_color)) # Updates Control Panel via signal and indicator via update()
            event.accept(); return
        # --- END NORMAL Mode Color Shortcuts ---

        # --- Tool Selection (no modifiers) ---
        if not ctrl_pressed and not alt_pressed and not shift_pressed:
            new_tool = None
            if key == Qt.Key_R: new_tool = "rect"
            elif key == Qt.Key_E: new_tool = "ellipse"
            elif key == Qt.Key_T: new_tool = "triangle"
            elif key == Qt.Key_L: new_tool = "line"
            elif key == Qt.Key_A: new_tool = "arrow"
            elif key == Qt.Key_P: new_tool = "polygon"
            elif key == Qt.Key_M: new_tool = "line_point"
            elif key == Qt.Key_B: new_tool = "brush"
            elif key == Qt.Key_X: new_tool = "text"

            if new_tool and new_tool != self.current_tool:
                self.current_tool = new_tool; tool_changed = True
                if self.current_tool in ["polygon", "line_point"]: self.polygon_points.clear()
                print(f"Tool changed to: {self.current_tool}")
                self.unsetCursor()
                if self.control_panel and self.current_tool in self.control_panel.tool_buttons:
                    self.control_panel.tool_buttons[self.current_tool].setChecked(True)
                self.current_drawing_shape = None; self.brush_points = []
                self.dragging = False; self.resizing = False
                self.update()
                event.accept(); return

        # --- File/Scene Actions ---
        if key == Qt.Key_C and shift_pressed and not ctrl_pressed and not alt_pressed:
            self.clear_scene(); event.accept(); return
        if key == Qt.Key_S and ctrl_pressed:
            filename, _ = QFileDialog.getSaveFileName(self, "Save Scene", "", "JSON Files (*.json)")
            if filename: self.save_scene(filename); event.accept(); return
        if key == Qt.Key_L and ctrl_pressed:
            filename, _ = QFileDialog.getOpenFileName(self, "Load Scene", "", "JSON Files (*.json)")
            if filename: self.save_state('load', all_shapes_before=deepcopy(self.shapes)); self.load_scene(filename, join=False); event.accept(); return

        # --- Deletion ---
        if key == Qt.Key_Delete or key == Qt.Key_Backspace:
            # Exclude Numpad Delete if it was handled above
            if is_numpad_del_or_period:
                pass # Already handled by color picker logic
            elif self.selected_shapes:
                print(f"Deleting {len(self.selected_shapes)} selected shapes (Key: {key})")
                deleted_shapes_copies = []; original_indices = []
                valid_selected = [s for s in self.selected_shapes if s in self.shapes]
                for shape in valid_selected:
                     try:
                         index = self.shapes.index(shape); original_indices.append(index)
                         deleted_shapes_copies.append(deepcopy(shape))
                     except ValueError: pass
                if deleted_shapes_copies:
                    indices_to_remove = sorted(original_indices, reverse=True)
                    self.save_state('delete_selected', shapes_involved=deleted_shapes_copies, indices=original_indices)
                    for index in indices_to_remove:
                        if 0 <= index < len(self.shapes): self.shapes.pop(index)
                    self.selected_shapes.clear()
                    self._configure_mode(); self.update()
                else: print("No valid shapes found in selection to delete.")
                event.accept(); return

        # --- Transformations on Selected Shapes ---
        if self.selected_shapes:
            delta_x, delta_y = 0, 0; scale_factor = 1.0; rotation_delta = 0
            action_type = None; prev_props = {}
            nudge = 1 if not shift_pressed else 10

            if not ctrl_pressed and not alt_pressed: # Movement/Scale
                if key == Qt.Key_Left: delta_x = -nudge; action_type = 'move'
                elif key == Qt.Key_Right: delta_x = nudge; action_type = 'move'
                elif key == Qt.Key_Up: delta_y = -nudge; action_type = 'move'
                elif key == Qt.Key_Down: delta_y = nudge; action_type = 'move'
                elif key in (Qt.Key_Plus, Qt.Key_Equal): scale_factor = 1.02 if not shift_pressed else 1.1; action_type = 'scale'
                elif key == Qt.Key_Minus: scale_factor = 1.0 / (1.02 if not shift_pressed else 1.1); action_type = 'scale'
            elif key == Qt.Key_Left: # Rotation Left
                if ctrl_pressed: rotation_delta = -90; action_type = 'rotate'
                elif alt_pressed: rotation_delta = -1; action_type = 'rotate'
            elif key == Qt.Key_Right: # Rotation Right
                if ctrl_pressed: rotation_delta = 90; action_type = 'rotate'
                elif alt_pressed: rotation_delta = 1; action_type = 'rotate'

            if action_type:
                print(f"Performing {action_type} on {len(self.selected_shapes)} shapes")
                current_indices = []; prev_props = {}; changed_shapes = []
                for shape in self.selected_shapes:
                     try: shape_idx = self.shapes.index(shape)
                     except ValueError: continue
                     current_indices.append(shape_idx); changed_shapes.append(shape)
                     if action_type in ['move', 'scale', 'resize']: prev_props[shape_idx] = deepcopy(shape.geometry)
                     elif action_type == 'rotate': prev_props[shape_idx] = shape.rotation
                     else: prev_props[shape_idx] = None

                # Apply transformation
                for shape in changed_shapes:
                    if action_type == 'move':
                        if isinstance(shape.geometry, QRectF) and shape.geometry.isValid(): shape.geometry.translate(delta_x, delta_y)
                        elif isinstance(shape.geometry, list): shape.geometry = [QPointF(p.x() + delta_x, p.y() + delta_y) for p in shape.geometry if isinstance(p, QPointF)]
                    elif action_type == 'scale':
                        center = QPointF(); geo = shape.geometry
                        if isinstance(geo, QRectF) and geo.isValid(): center = geo.center()
                        elif isinstance(geo, list): pts = [p for p in geo if isinstance(p, QPointF)]; center = QPointF(sum(p.x() for p in pts)/len(pts), sum(p.y() for p in pts)/len(pts)) if pts else QPointF()
                        if not center.isNull():
                            tf = QTransform().translate(center.x(), center.y()).scale(scale_factor, scale_factor).translate(-center.x(), -center.y())
                            if isinstance(geo, QRectF) and geo.isValid(): shape.geometry = tf.mapRect(geo)
                            elif isinstance(geo, list): shape.geometry = [tf.map(p) for p in geo if isinstance(p, QPointF)]
                    elif action_type == 'rotate': shape.rotation = (shape.rotation + rotation_delta) % 360

                if current_indices and prev_props:
                    self.save_state(action_type, shapes_involved=changed_shapes, previous_geometries=prev_props, indices=current_indices)
                self._configure_mode(); self.update()
                event.accept(); return

        # Update view if Alt+Arrow pressed for rotation angle display
        if alt_pressed and key in (Qt.Key_Left, Qt.Key_Right):
             self.update() # Update for angle display
             event.accept(); return

        # If event was not handled, pass it up
        super().keyPressEvent(event)


    def keyReleaseEvent(self, event: QKeyEvent):
        key = event.key()
        if key in self.pressed_keys:
            try: self.pressed_keys.remove(key)
            except KeyError: pass
        # Redraw if Alt was released (to hide angle display)
        if key == Qt.Key_Alt and self.selected_shapes and self.drawing_mode:
             self.update()
             event.accept(); return
        super().keyReleaseEvent(event)


    def closeEvent(self, event):
        """Ensure hotkey is unregistered on close."""
        print("Overlay closeEvent called.")
        self._unregister_global_hotkey()
        super().closeEvent(event)

    # --- Copy/Paste Methods ---
    def copy_shapes(self):
        if not self.selected_shapes: return
        self.clipboard_shapes = [deepcopy(s) for s in self.selected_shapes if s in self.shapes]
        print(f"Copied {len(self.clipboard_shapes)} shapes.")

    def paste_shapes(self):
        if not self.clipboard_shapes: return
        print(f"Pasting {len(self.clipboard_shapes)} shapes...")
        mouse_pos_local = self.mapFromGlobal(QCursor.pos())
        pasted_shapes_for_undo = []
        new_indices = []

        all_points = []; all_rects = []
        for shape in self.clipboard_shapes:
             if isinstance(shape.geometry, QRectF) and shape.geometry.isValid(): all_rects.append(shape.geometry)
             elif isinstance(shape.geometry, list): all_points.extend([p for p in shape.geometry if isinstance(p, QPointF)])

        clip_center = QPointF()
        if all_rects or all_points:
             min_x, min_y = float('inf'), float('inf'); max_x, max_y = float('-inf'), float('-inf')
             for r in all_rects: min_x=min(min_x,r.left()); min_y=min(min_y,r.top()); max_x=max(max_x,r.right()); max_y=max(max_y,r.bottom())
             for p in all_points: min_x=min(min_x,p.x()); min_y=min(min_y,p.y()); max_x=max(max_x,p.x()); max_y=max(max_y,p.y())
             if min_x != float('inf'): clip_center = QPointF((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
             else: clip_center = mouse_pos_local # Fallback if no valid geometry

        paste_offset = QPointF(mouse_pos_local) - clip_center
        # Save state *before* pasting for undo
        shapes_before_paste = deepcopy(self.shapes)

        for shape in self.clipboard_shapes:
            new_shape = deepcopy(shape)
            if isinstance(new_shape.geometry, QRectF) and new_shape.geometry.isValid(): new_shape.geometry.translate(paste_offset)
            elif isinstance(new_shape.geometry, list): new_shape.geometry = [p + paste_offset for p in new_shape.geometry if isinstance(p, QPointF)]
            self.shapes.append(new_shape)
            pasted_shapes_for_undo.append(new_shape)
            new_indices.append(len(self.shapes) - 1)

        # Pass shapes *before* paste for undo, and count for redo simplicity
        self.save_state('paste',
                        shapes_involved=shapes_before_paste, # State before paste
                        previous_geometries=len(pasted_shapes_for_undo)) # Use this field for count

        self.selected_shapes = pasted_shapes_for_undo[:]
        self._configure_mode(); self.update()
        print(f"Pasted {len(pasted_shapes_for_undo)} shapes.")
    # --- End Copy/Paste Methods ---


    def show_text_dialog(self, pos_or_origin, shape_to_edit=None, initial_props=None, initial_rect=None):
        """Shows text dialog for editing or creating text shapes."""
        if shape_to_edit: # Editing existing
            shape_index = -1
            try: shape_index = self.shapes.index(shape_to_edit)
            except ValueError: print("Warning: Shape to edit not found in list."); return

            print(f"Editing text shape at index {shape_index}")
            # Ensure existing props are copied deeply (initial_props already passed in)
            current_props_copy = deepcopy(initial_props) if initial_props else \
                                 deepcopy(self.board_default_text_properties if self.board_mode else self.default_text_properties)
            dialog = TextInputDialog(self, existing_properties=current_props_copy)
            original_props_for_undo = {'text_properties': deepcopy(shape_to_edit.text_properties), 'geometry': deepcopy(shape_to_edit.geometry)}

            if dialog.exec():
                new_props = dialog.get_properties()
                text = new_props.get('text', '')

                if hasattr(dialog, 'text_cleared') and dialog.text_cleared and not text:
                    print(f"Deleting text shape {shape_index} due to Clear+OK.")
                    try:
                        shape_copy = deepcopy(shape_to_edit)
                        self.shapes.pop(shape_index)
                        if shape_to_edit in self.selected_shapes: self.selected_shapes.remove(shape_to_edit)
                        self.save_state('delete', shapes_involved=[shape_copy], indices=[shape_index])
                        self._configure_mode(); self.update()
                        return
                    except Exception as e: print(f"Error deleting shape: {e}")
                    return

                # --- Update Default Properties (Mode Dependent) ---
                prev_defaults_for_undo = None
                if not self.board_mode:
                     self.default_text_properties = deepcopy(new_props)
                     self.default_text_properties['text'] = '' # Don't save the specific text as default
                     self.defaults_changed.emit() # Signal control panel to update ONLY in NORMAL mode
                     print("Updated NORMAL text defaults & signaled panel.")
                else:
                     # Save the state before changing BOARD defaults
                     prev_defaults_for_undo = deepcopy(self.board_default_text_properties)
                     self.board_default_text_properties = deepcopy(new_props)
                     self.board_default_text_properties['text'] = ''
                     # Save undo state for the default change itself
                     self.save_state('change_board_text_defaults', previous_geometries={'board_text_defaults': prev_defaults_for_undo})
                     print("Updated BOARD text defaults (applied to shape, not signaling panel).")
                # --- End Update Defaults ---

                if text: # Update shape only if text is not empty
                    shape_to_edit.text_properties = new_props
                    # Recalculate geometry based on new text and properties
                    font = QFont(new_props.get('font', 'Arial'), new_props.get('size', 12)); font.setBold(new_props.get('bold', False)); font.setItalic(new_props.get('italic', False)); font.setUnderline(new_props.get('underline', False)); font.setStrikeOut(new_props.get('strikeout', False))
                    metrics = QFontMetrics(font)
                    flags = Qt.TextWordWrap; align_str = new_props.get('alignment', 'left'); flags |= {'left': Qt.AlignLeft, 'center': Qt.AlignCenter, 'right': Qt.AlignRight, 'justify': Qt.AlignJustify}.get(align_str, Qt.AlignLeft); flags |= Qt.AlignVCenter
                    # Use a generous width for calculation, height doesn't matter much here
                    bounding_rect_text = metrics.boundingRect(QRectF(0,0, 10000, 10000), flags, text)
                    current_geom = shape_to_edit.geometry
                    # Use calculated size with padding, ensure minimums
                    new_width = max(bounding_rect_text.width() + 10, 30)
                    new_height = max(bounding_rect_text.height() + 6, 20)
                    shape_to_edit.geometry = QRectF(current_geom.topLeft(), QSizeF(new_width, new_height))

                    # Save Undo State for the shape edit
                    self.save_state('edit_text', shapes_involved=[shape_to_edit], previous_geometries={shape_index: original_props_for_undo}, indices=[shape_index])
                    self._configure_mode(); self.update()

                    # --- Auto-exit drawing mode ---
                    if not self.board_mode:
                         print("Auto-exiting drawing mode after text edit.")
                         self.set_drawing_mode(False)
                    # --- End Auto-exit ---
                else: # Text empty after edit
                    print("Text edit resulted in empty text. Defaults possibly saved, shape not changed.")
                    self.update()
            else: print("Text edit dialog cancelled")

        else: # Creating new text
            origin_pos = pos_or_origin if isinstance(pos_or_origin, QPointF) else QPointF(0,0)
            print(f"Showing text dialog for new text at pos={origin_pos}")
            # Ensure initial props are copied deeply
            current_props_copy = deepcopy(initial_props) if initial_props else \
                                 deepcopy(self.board_default_text_properties if self.board_mode else self.default_text_properties)
            dialog = TextInputDialog(self, existing_properties=current_props_copy)
            if dialog.exec():
                if hasattr(dialog, 'text_cleared') and dialog.text_cleared: print("Text creation cancelled via Clear+OK."); return

                props = dialog.get_properties()
                text = props.get('text', '')

                # --- Update Default Properties (Mode Dependent) ---
                prev_defaults_for_undo = None
                if not self.board_mode:
                     self.default_text_properties = deepcopy(props)
                     self.default_text_properties['text'] = '' # Don't save the specific text as default
                     self.defaults_changed.emit()
                     print("Updated NORMAL text defaults & signaled panel.")
                else:
                    prev_defaults_for_undo = deepcopy(self.board_default_text_properties)
                    self.board_default_text_properties = deepcopy(props)
                    self.board_default_text_properties['text'] = ''
                    self.save_state('change_board_text_defaults', previous_geometries={'board_text_defaults': prev_defaults_for_undo})
                    print("Updated BOARD text defaults (applied to shape, not signaling panel).")
                # --- End Update Defaults ---

                if text: # Create shape only if text is not empty
                    font = QFont(props.get('font', 'Arial'), props.get('size', 12)); font.setBold(props.get('bold', False)); font.setItalic(props.get('italic', False)); font.setUnderline(props.get('underline', False)); font.setStrikeOut(props.get('strikeout', False))
                    metrics = QFontMetrics(font)
                    flags = Qt.TextWordWrap; align_str = props.get('alignment', 'left'); flags |= {'left': Qt.AlignLeft, 'center': Qt.AlignCenter, 'right': Qt.AlignRight, 'justify': Qt.AlignJustify}.get(align_str, Qt.AlignLeft); flags |= Qt.AlignVCenter
                    bounding_rect_text = metrics.boundingRect(QRect(0, 0, 10000, 10000), flags, text)
                    text_width = max(bounding_rect_text.width() + 10, 50)
                    text_height = max(bounding_rect_text.height() + 6, 20)

                    # Use initial_rect if provided (from drag), otherwise use origin_pos
                    final_rect = initial_rect if initial_rect and initial_rect.isValid() else QRectF(origin_pos, QSizeF(text_width, text_height))
                    # Ensure final rect uses calculated size, keeping the top-left from initial_rect/origin_pos
                    final_rect.setSize(QSizeF(text_width, text_height))


                    # Use appropriate color and alpha based on mode
                    text_color = QColor(props['color'])
                    if not text_color.isValid(): text_color = Qt.black
                    # Alpha from normal mode settings (no separate board alpha for shapes yet)
                    text_alpha = self.current_alpha

                    text_shape = Shape('text', final_rect, text_color, filled=False, alpha=text_alpha, line_thickness=0, line_style=Qt.SolidLine, text_properties=props)
                    self.shapes.append(text_shape)
                    self.save_state('draw', shapes_involved=[text_shape], indices=[len(self.shapes)-1])
                    self._configure_mode(); self.update()

                    # --- Auto-exit drawing mode ---
                    if not self.board_mode:
                         print("Auto-exiting drawing mode after new text.")
                         self.set_drawing_mode(False)
                    # --- End Auto-exit ---
                else:
                    print("Text input empty, shape not created (defaults possibly saved).")
            else: print("Text dialog cancelled")


    def save_scene(self, filename):
        print(f"Saving scene to {filename}")
        try:
            scene_data = []
            for i, shape in enumerate(self.shapes):
                 if shape:
                      try:
                          shape_dict = shape.to_dict()
                          if shape_dict: # Ensure dict was created successfully
                              scene_data.append(shape_dict)
                          else:
                              print(f"Warning: Failed to serialize shape {i} (returned None)")
                      except Exception as e: print(f"Error serializing shape {i}: {e}")
                 else: print(f"Warning: Found None shape at index {i} during save.")

            with open(filename, 'w', encoding='utf-8') as f: json.dump(scene_data, f, indent=4)
            print(f"Scene saved successfully ({len(scene_data)} shapes).")
        except Exception as e: print(f"Error saving scene: {e}"); traceback.print_exc()


    def load_scene(self, filename, join=False): # Added join parameter
        print(f"Loading scene from {filename} (Join={join})")
        try:
            with open(filename, 'r', encoding='utf-8') as f: scene_data = json.load(f)
            if not isinstance(scene_data, list):
                 print(f"Error: Loaded data is not a list. Aborting load.")
                 return

            if not join:
                print("Replacing current scene.")
                self.shapes.clear(); self.selected_shapes.clear(); self.current_drawing_shape = None
                self.polygon_points.clear(); self.brush_points.clear()
            else:
                print("Joining loaded scene with current scene.")
                self.selected_shapes.clear() # Clear selection when joining

            loaded_shapes = []
            for i, shape_data in enumerate(scene_data):
                 if isinstance(shape_data, dict):
                      shape = Shape.from_dict(shape_data)
                      if shape: loaded_shapes.append(shape)
                      else: print(f"Warning: Failed to load shape {i} from dict: {shape_data}")
                 else: print(f"Warning: Invalid shape data format (not a dict) at index {i}: {shape_data}")

            if join: self.shapes.extend(loaded_shapes)
            else: self.shapes = loaded_shapes

            self._configure_mode(); self.update()
            print(f"Scene loaded with {len(self.shapes)} shapes total.")
        except json.JSONDecodeError as e:
             print(f"Error decoding JSON from {filename}: {e}")
             QMessageBox.warning(self, "Load Error", f"Could not decode JSON file:\n{filename}\n\n{e}")
        except Exception as e:
             print(f"Error loading scene: {e}"); traceback.print_exc()
             QMessageBox.warning(self, "Load Error", f"An unexpected error occurred loading the scene:\n{e}")


    def clear_scene(self, save_undo=True):
        """Clears all shapes from the scene."""
        print("Clearing scene...")
        if self.shapes:
            if save_undo: self.save_state('clear', all_shapes_before=deepcopy(self.shapes))
            self.shapes.clear(); self.current_drawing_shape = None; self.selected_shapes.clear()
            self.polygon_points.clear(); self.brush_points.clear()
            self.dragging = False; self.resizing = False
            self._configure_mode(); self.update()
            print("Scene cleared.")
        else: print("Scene already empty.")

# --- Klasa TextInputDialog ---
class TextInputDialog(QDialog):
    def __init__(self, parent, existing_properties=None):
        super().__init__(parent)
        self.setWindowTitle("Text Properties")
        self.setModal(True)
        props = deepcopy(existing_properties) if existing_properties is not None else {}
        self.text_cleared = False
        layout = QVBoxLayout(self)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(props.get('text', ''))
        layout.addWidget(QLabel("Text:"))
        layout.addWidget(self.text_edit)

        font_layout = QHBoxLayout()
        self.font_combo = QFontComboBox()
        try:
            font = QFont(props.get('font', 'Arial'))
            self.font_combo.setCurrentFont(font)
        except Exception as e:
            print(f"Warning: Could not set font '{props.get('font', 'Arial')}', using default. Error: {e}")
            self.font_combo.setCurrentFont(QFont('Arial'))
        font_layout.addWidget(QLabel("Font:")); font_layout.addWidget(self.font_combo)

        self.size_spin = QSpinBox(); self.size_spin.setRange(6, 120); self.size_spin.setValue(props.get('size', 12)); self.size_spin.setSuffix(" pt")
        font_layout.addWidget(QLabel("Size:")); font_layout.addWidget(self.size_spin)
        layout.addLayout(font_layout)

        style_layout = QHBoxLayout()
        self.bold_check = QCheckBox("B"); f=self.bold_check.font(); f.setBold(True); self.bold_check.setFont(f); self.bold_check.setChecked(props.get('bold', False))
        self.italic_check = QCheckBox("I"); f=self.italic_check.font(); f.setItalic(True); self.italic_check.setFont(f); self.italic_check.setChecked(props.get('italic', False))
        self.underline_check = QCheckBox("U"); f=self.underline_check.font(); f.setUnderline(True); self.underline_check.setFont(f); self.underline_check.setChecked(props.get('underline', False))
        self.strikeout_check = QCheckBox("S"); f=self.strikeout_check.font(); f.setStrikeOut(True); self.strikeout_check.setFont(f); self.strikeout_check.setChecked(props.get('strikeout', False))
        style_layout.addWidget(self.bold_check); style_layout.addWidget(self.italic_check); style_layout.addWidget(self.underline_check); style_layout.addWidget(self.strikeout_check); style_layout.addStretch()
        layout.addLayout(style_layout)

        color_layout = QHBoxLayout()
        try:
            text_color_str = props.get('color', '#000000')
            self.text_color = QColor(text_color_str)
            if not self.text_color.isValid(): self.text_color = QColor('#000000')
        except Exception: self.text_color = QColor('#000000')
        self.text_color_button = QPushButton("Text Color"); self.text_color_button.clicked.connect(self.choose_text_color)
        color_layout.addWidget(self.text_color_button)

        bg_color_str = props.get('background_color'); self.bg_color = None
        if bg_color_str:
            try:
                temp_color = QColor(bg_color_str)
                # Treat fully transparent as None
                if temp_color.isValid() and temp_color.alpha() != 0:
                     self.bg_color = temp_color
            except Exception: self.bg_color = None
        self.bg_color_button = QPushButton(); self.bg_color_button.clicked.connect(self.choose_bg_color)
        color_layout.addWidget(self.bg_color_button)

        self.transparent_bg_button = QPushButton("Transparent"); self.transparent_bg_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed); self.transparent_bg_button.clicked.connect(self.set_bg_transparent)
        color_layout.addWidget(self.transparent_bg_button)
        color_layout.addStretch(); layout.addLayout(color_layout)
        self.update_text_color_button_style(); self.update_bg_color_button_style(); self.update_transparent_button_style()

        align_layout = QHBoxLayout(); self.align_combo = QComboBox(); self.align_combo.addItems(['left', 'center', 'right', 'justify'])
        current_align = props.get('alignment', 'left'); current_align = current_align if current_align in ['left', 'center', 'right', 'justify'] else 'left'; self.align_combo.setCurrentText(current_align)
        align_layout.addWidget(QLabel("Alignment:")); align_layout.addWidget(self.align_combo); align_layout.addStretch(); layout.addLayout(align_layout)

        button_layout = QHBoxLayout()
        info_label = QLabel("<small><i>Clear & OK = DELETE Shape (if empty)</i></small>"); info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter); button_layout.addWidget(info_label); button_layout.addStretch()
        clear_button = QPushButton("Clear"); clear_button.clicked.connect(self.on_clear_button_clicked)
        clear_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed); button_layout.addWidget(clear_button)
        ok_button = QPushButton("OK"); ok_button.clicked.connect(self.accept); ok_button.setDefault(True); ok_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject); cancel_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        button_layout.addWidget(ok_button); button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.setMinimumWidth(400); self.text_edit.setFocus()

    @Slot()
    def on_clear_button_clicked(self): self.text_edit.clear(); self.text_cleared = True
    @Slot()
    def set_bg_transparent(self): self.bg_color = None; self.update_bg_color_button_style(); self.update_transparent_button_style()

    def update_text_color_button_style(self):
        if not hasattr(self, 'text_color') or not self.text_color.isValid(): bg_color_css="#000000"; text_color_css="white"
        else: bg_color_css = self.text_color.name(QColor.HexRgb); text_color_css = 'white' if self.text_color.lightnessF() < 0.5 else 'black'
        self.text_color_button.setStyleSheet(f"background-color: {bg_color_css}; color: {text_color_css}; border: 1px solid grey; padding: 3px;"); self.text_color_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def update_bg_color_button_style(self):
        if hasattr(self, 'bg_color') and self.bg_color and self.bg_color.isValid() and self.bg_color.alpha() > 0:
            color_name = self.bg_color.name(QColor.HexArgb); text_color = 'white' if self.bg_color.lightnessF() < 0.5 else 'black'; self.bg_color_button.setText("BG Color")
            self.bg_color_button.setStyleSheet(f"background-color: {color_name}; color: {text_color}; border: 1px solid grey; padding: 3px;"); self.bg_color_button.setToolTip(f"Current BG: {color_name}")
        else:
            self.bg_color_button.setText("BG Color"); self.bg_color_button.setStyleSheet("background-color: none; color: black; border: 1px dashed grey; padding: 3px;"); self.bg_color_button.setToolTip("Current BG: None")
        self.bg_color_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def update_transparent_button_style(self):
        is_transparent = not (hasattr(self, 'bg_color') and self.bg_color and self.bg_color.isValid() and self.bg_color.alpha() > 0)
        self.transparent_bg_button.setStyleSheet(f"border: { '2px solid red' if is_transparent else '1px solid grey' }; padding: 3px;")

    def choose_text_color(self):
        # Ensure text_color is valid before passing to dialog
        initial_text_color = self.text_color if hasattr(self, 'text_color') and self.text_color.isValid() else QColor(Qt.black)
        color = QColorDialog.getColor(initial_text_color, self, "Choose Text Color")
        if color.isValid(): self.text_color = color; self.update_text_color_button_style()

    def choose_bg_color(self):
        initial_color = self.bg_color if hasattr(self, 'bg_color') and self.bg_color and self.bg_color.isValid() else QColor(Qt.white)
        if initial_color.alpha() == 0: initial_color.setAlpha(255) # Start picker opaque if current is transparent
        color = QColorDialog.getColor(initial_color, self, "Choose Background Color", QColorDialog.ShowAlphaChannel)
        if color.isValid(): self.bg_color = None if color.alpha() == 0 else color
        self.update_bg_color_button_style(); self.update_transparent_button_style()

    def get_properties(self):
        bg_color_val = self.bg_color.name(QColor.HexArgb) if hasattr(self, 'bg_color') and self.bg_color and self.bg_color.isValid() else None
        text_color_val = self.text_color.name(QColor.HexRgb) if hasattr(self, 'text_color') and self.text_color.isValid() else '#000000'
        return deepcopy({
            'text': self.text_edit.toPlainText(),
            'font': self.font_combo.currentFont().family(),
            'size': self.size_spin.value(),
            'bold': self.bold_check.isChecked(),
            'italic': self.italic_check.isChecked(),
            'underline': self.underline_check.isChecked(),
            'strikeout': self.strikeout_check.isChecked(),
            'color': text_color_val,
            'background_color': bg_color_val,
            'alignment': self.align_combo.currentText()
        })

# --- Klasa ControlPanel ---
class ControlPanel(QDockWidget):
    def __init__(self, overlay):
        super().__init__("Draw Desktop")
        self.overlay = overlay
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable)
        self.setFloating(True)
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint | Qt.WindowSystemMenuHint)
        self.shortcuts_window = None
        self.settings = QSettings("MyCompany", "DesktopOverlayRGN") # Keep using this for panel settings

        self._dragging_window = False
        self._drag_window_offset = QPoint()

        widget = QWidget(); self.setWidget(widget)
        layout = QVBoxLayout(widget); layout.setSpacing(5); layout.setContentsMargins(5, 5, 5, 5)

        # --- Define UI elements (order matters for layout) ---
        # Alpha/Transparency
        alpha_layout = QHBoxLayout(); alpha_layout.addWidget(QLabel("Transparency:"))
        self.alpha_spin = QSpinBox(); self.alpha_spin.setRange(0, 255); self.alpha_spin.setToolTip("Shape Opacity (0=Transparent, 255=Opaque)")
        alpha_layout.addWidget(self.alpha_spin); alpha_layout.addStretch(); layout.addLayout(alpha_layout)

        # Thickness
        thickness_layout = QHBoxLayout(); thickness_layout.addWidget(QLabel("Thickness:"))
        self.thickness_spin = QSpinBox(); self.thickness_spin.setRange(1, 50)
        thickness_layout.addWidget(self.thickness_spin); thickness_layout.addStretch(); layout.addLayout(thickness_layout)

        # Arrow Head Size
        arrow_size_layout = QHBoxLayout(); arrow_size_layout.addWidget(QLabel("Arrow Head:"))
        self.arrow_size_spin = QSpinBox(); self.arrow_size_spin.setRange(1, 100)
        arrow_size_layout.addWidget(self.arrow_size_spin); arrow_size_layout.addStretch(); layout.addLayout(arrow_size_layout)

        # Brush Size
        brush_size_layout = QHBoxLayout(); brush_size_layout.addWidget(QLabel("Brush Size:"))
        self.brush_size_spin = QSpinBox(); self.brush_size_spin.setRange(1, 100)
        brush_size_layout.addWidget(self.brush_size_spin); brush_size_layout.addStretch(); layout.addLayout(brush_size_layout)

        # Line Style
        style_layout = QHBoxLayout(); style_layout.addWidget(QLabel("Style:"))
        self.style_combo = QComboBox(); self.style_combo.addItem("Solid", Qt.SolidLine); self.style_combo.addItem("Dot", Qt.DotLine); self.style_combo.addItem("Dash", Qt.DashLine)
        style_layout.addWidget(self.style_combo); style_layout.addStretch(); layout.addLayout(style_layout)

        # Fill (Applies in Both Modes for relevant shapes)
        self.fill_check = QCheckBox("Fill Shapes"); self.fill_check.setToolTip("Fill Rectangles, Ellipses, Triangles, Polygons")
        layout.addWidget(self.fill_check)

        # Dimm (Normal Mode Only)
        self.dim_check = QCheckBox("Dimm"); self.dim_check.setToolTip("Dim background in Normal drawing mode")
        layout.addWidget(self.dim_check)

        # Tool Text/Indicators Toggle (Applies Visually in Both Modes)
        self.tool_text_check = QCheckBox("Show Indicators"); self.tool_text_check.setToolTip("Show tool name and mode indicators")
        layout.addWidget(self.tool_text_check)

        # --- Tools ---
        tool_frame = QFrame(); tool_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Plain)
        tool_layout_inner = QVBoxLayout(tool_frame); tool_layout_inner.setSpacing(2); tool_layout_inner.setContentsMargins(4,4,4,4)
        tool_layout_inner.addWidget(QLabel("<b>Tools:</b>"))
        self.tools_config = [ ("Rectangle (R)", "rect"), ("Ellipse (E)", "ellipse"), ("Triangle (T)", "triangle"), ("Line Single (L)", "line"), ("Line Point (M)", "line_point"), ("Arrow (A)", "arrow"), ("Polygon (P)", "polygon"), ("Brush (B)", "brush"), ("Text (X)", "text") ]
        self.tool_buttons = {}; self.tool_group = QButtonGroup(widget)
        for label, tool_name in self.tools_config:
            btn = QRadioButton(label); btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            self.tool_buttons[tool_name] = btn; self.tool_group.addButton(btn)
            btn.toggled.connect(lambda checked, t=tool_name: self.set_tool(t) if checked else None)
            tool_layout_inner.addWidget(btn)
        layout.addWidget(tool_frame)

        # --- Action Buttons ---
        layout.addStretch()
        action_column_layout = QVBoxLayout(); action_column_layout.setSpacing(3)

        # Create buttons
        self.drawing_button = QPushButton("DRAW (Alt+F1)"); self.drawing_button.setCheckable(True); self.drawing_button.setToolTip("Toggle Drawing Mode (Alt+F1)")
        edit_button = QPushButton("EDIT (Alt+F2)"); edit_button.setToolTip("Enter Edit Mode (Board with Transparent BG) (Alt+F2)"); edit_button.clicked.connect(self.overlay.enter_edit_mode)
        board_button = QPushButton("BOARD (Alt+F3)"); board_button.setToolTip("Enter Whiteboard Mode (Alt+F3)"); board_button.clicked.connect(self.overlay.enter_board_mode)

        # --- Color Buttons ---
        self.edit_color_button = QPushButton("Color (Edit)"); self.edit_color_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed); self.edit_color_button.clicked.connect(self.choose_edit_color)
        self.draw_color_button = QPushButton("Color Draw"); self.draw_color_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed); self.draw_color_button.clicked.connect(self.choose_draw_color)
        # --- ---

        save_button = QPushButton("Save"); save_button.setToolTip("Save Scene (Ctrl+S)"); save_button.clicked.connect(self.save_scene_action)
        load_button = QPushButton("Load"); load_button.setToolTip("Load Scene (Replace) (Ctrl+L)"); load_button.clicked.connect(self.load_scene_action)
        load_join_button = QPushButton("Load&Join"); load_join_button.setToolTip("Load Scene (Append)"); load_join_button.clicked.connect(self.load_and_join_scene_action)
        clear_button = QPushButton("Clear"); clear_button.setToolTip("Clear Scene (Shift+C)"); clear_button.clicked.connect(self.overlay.clear_scene)
        undo_button = QPushButton("Undo"); undo_button.setToolTip("Undo Last Action (Ctrl+Z)"); undo_button.clicked.connect(self.overlay.undo)
        redo_button = QPushButton("Redo"); redo_button.setToolTip("Redo Last Undone Action (Ctrl+Y / Ctrl+Shift+Z)"); redo_button.clicked.connect(self.overlay.redo)
        shortcuts_button = QPushButton("KEYS (Ctrl+K)"); shortcuts_button.clicked.connect(lambda: self.toggle_shortcuts_window(force_reset=False)) # Don't force reset on button click


        # *** Button Order: Color, File, Edit, Mode, Draw last ***
        action_buttons = [
            self.edit_color_button, # New Edit Color Button
            self.draw_color_button, # Renamed Draw Color Button
            save_button,
            load_button,
            load_join_button,
            clear_button,
            undo_button,
            redo_button,
            shortcuts_button,
            board_button, # BOARD (Alt+F3)
            edit_button,  # EDIT (Alt+F2)
            self.drawing_button, # DRAW (Alt+F1) last
        ]
        # *** END Button Order ***

        for btn in action_buttons:
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            action_column_layout.addWidget(btn)
        layout.addLayout(action_column_layout)

        self.original_drawing_button_style = self.drawing_button.styleSheet()
        self.active_drawing_button_style = "background-color: lightgreen;"

        # --- Connect Signals ---
        self.drawing_button.toggled.connect(self.handle_draw_mode_toggle)
        self.overlay.drawing_mode_changed.connect(self.update_draw_button_state)
        self.overlay.color_changed.connect(self.update_draw_color_button_style) # Normal mode color
        self.overlay.board_color_changed.connect(self.update_edit_color_button_style) # Board mode color
        self.alpha_spin.valueChanged.connect(self.overlay.set_alpha)
        self.thickness_spin.valueChanged.connect(self.overlay.set_line_thickness)
        self.style_combo.activated.connect(self.on_style_combo_activated)
        self.arrow_size_spin.valueChanged.connect(self.overlay.set_arrow_head_size)
        self.brush_size_spin.valueChanged.connect(self.set_brush_size)
        self.fill_check.stateChanged.connect(self.update_fill_state) # Connect fill checkbox
        self.dim_check.stateChanged.connect(lambda state: self.overlay.set_dim_background(state == Qt.Checked))
        self.tool_text_check.stateChanged.connect(lambda state: self.overlay.set_show_tool_text(state == Qt.Checked))
        self.overlay.defaults_changed.connect(self.update_controls_from_defaults)

        # --- Final Setup ---
        self.overlay.control_panel = self
        self.restore_settings() # Restore AFTER UI elements created & signals connected
        print("ControlPanel initialized and settings restored.")

    # --- Mouse Events for Window Dragging ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            title_bar_height = self.style().pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight) if self.style() else 20
            is_on_title_bar = event.position().y() <= title_bar_height
            if not is_on_title_bar:
                child = self.childAt(event.position().toPoint()); is_interactive = False
                if child:
                    current_widget = child
                    while current_widget and current_widget != self.widget():
                        # Expanded list of potentially interactive widget types
                        interactive_types = [
                            "QPushButton", "QRadioButton", "QCheckBox", "QSpinBox",
                            "QComboBox", "QLineEdit", "QTextEdit", "QSlider",
                            "QAbstractSpinBox", "QToolButton", "QAbstractSlider",
                            "QDial", "QScrollBar"
                        ]
                        if any(current_widget.inherits(t) for t in interactive_types):
                            is_interactive = True; break
                        current_widget = current_widget.parentWidget()
                if not is_interactive:
                    self._dragging_window = True
                    # Use globalPosition for reliable drag offset calculation
                    self._drag_window_offset = event.globalPosition().toPoint() - self.geometry().topLeft()
                    self.setCursor(Qt.SizeAllCursor)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging_window and event.buttons() & Qt.LeftButton:
            # Use globalPosition for reliable window moving
            self.move(event.globalPosition().toPoint() - self._drag_window_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._dragging_window:
             self._dragging_window = False
             self.unsetCursor()
             event.accept()
             return
        super().mouseReleaseEvent(event)
    # --- End Mouse Events for Window Dragging ---


    def restore_settings(self):
        """Load settings from QSettings and apply them."""
        print("Restoring control panel settings...")
        geom = self.settings.value("controlPanel/geometry")
        if geom and isinstance(geom, QRect):
            available_geom = QGuiApplication.primaryScreen().availableGeometry(); adjusted_geom = geom.adjusted(-5, -5, 5, 5)
            if available_geom.intersects(adjusted_geom): self.setGeometry(geom); print(f"Restored geometry: {geom}")
            else: print("Saved geometry off-screen. Using default."); QTimer.singleShot(100, self.adjust_position)
        else: QTimer.singleShot(100, self.adjust_position); print("No saved geometry, using default.")

        # Block signals temporarily to avoid redundant updates during restore
        self.overlay.blockSignals(True)
        self.alpha_spin.blockSignals(True)
        self.thickness_spin.blockSignals(True)
        self.style_combo.blockSignals(True)
        self.arrow_size_spin.blockSignals(True)
        self.brush_size_spin.blockSignals(True)
        self.fill_check.blockSignals(True)
        self.dim_check.blockSignals(True)
        self.tool_text_check.blockSignals(True)

        # Restore Draw Mode Color
        default_draw_color_str = QColor(255, 0, 0).name(QColor.HexArgb) # Default Red
        saved_draw_color_str = self.settings.value("controlPanel/drawPenColor", default_draw_color_str)
        restored_draw_color = QColor(saved_draw_color_str); restored_draw_color = restored_draw_color if restored_draw_color.isValid() else QColor(default_draw_color_str)
        self.overlay.set_pen_color(restored_draw_color) # Set internal value

        # Restore Board/Edit Mode Color (from board settings)
        default_edit_color_str = QColor(Qt.black).name(QColor.HexArgb)
        self.settings.beginGroup("board")
        saved_edit_color_str = self.settings.value("penColor", default_edit_color_str)
        self.settings.endGroup()
        restored_edit_color = QColor(saved_edit_color_str)
        restored_edit_color = restored_edit_color if restored_edit_color.isValid() else QColor(default_edit_color_str)
        self.overlay.set_board_pen_color(restored_edit_color) # Set internal board color value

        # Restore other settings
        saved_tool = self.settings.value("controlPanel/currentTool", self.overlay.current_tool)
        saved_alpha = self.settings.value("controlPanel/alpha", self.overlay.current_alpha, type=int)
        saved_thickness = self.settings.value("controlPanel/thickness", self.overlay.current_line_thickness, type=int)
        saved_style_value = self.settings.value("controlPanel/lineStyleValue", Qt.SolidLine.value, type=int)
        saved_arrow_size = self.settings.value("controlPanel/arrowSize", self.overlay.current_arrow_head_size, type=int)
        saved_brush_size = self.settings.value("controlPanel/brushSize", self.overlay.brush_size, type=int)
        saved_fill_state = self.settings.value("controlPanel/fillChecked", True, type=bool)
        saved_dimm_state = self.settings.value("controlPanel/dimmChecked", True, type=bool)
        saved_tool_text_state = self.settings.value("controlPanel/showToolText", True, type=bool)

        # Restore Default Text Properties (Normal Mode) from settings
        default_props = self.overlay.default_text_properties
        self.settings.beginGroup("textDefaults") # Read from the normal text defaults group
        default_props['font'] = self.settings.value("font", default_props['font'])
        default_props['size'] = self.settings.value("size", default_props['size'], type=int)
        default_props['bold'] = self.settings.value("bold", default_props['bold'], type=bool)
        default_props['italic'] = self.settings.value("italic", default_props['italic'], type=bool)
        default_props['underline'] = self.settings.value("underline", default_props['underline'], type=bool)
        default_props['strikeout'] = self.settings.value("strikeout", default_props['strikeout'], type=bool)
        default_props['color'] = self.settings.value("color", default_props['color'])
        bg_color_setting = self.settings.value("backgroundColor")
        default_props['background_color'] = bg_color_setting if bg_color_setting is not None else None
        default_props['alignment'] = self.settings.value("alignment", default_props['alignment'])
        self.settings.endGroup()
        self.overlay.default_text_properties = default_props # Update overlay's defaults
        print(f"Restored NORMAL default text properties: {self.overlay.default_text_properties}")

        # --- Apply restored values to UI elements and overlay internal state ---
        self.set_tool(saved_tool) # This updates the overlay tool internally
        self.alpha_spin.setValue(saved_alpha); self.overlay.set_alpha(saved_alpha)
        self.thickness_spin.setValue(saved_thickness); self.overlay.set_line_thickness(saved_thickness)

        try: saved_style_enum = Qt.PenStyle(saved_style_value); found_index = self.style_combo.findData(saved_style_enum)
        except ValueError: found_index = -1; print(f"Invalid style value {saved_style_value} in settings.")

        if found_index != -1:
            self.style_combo.setCurrentIndex(found_index)
            self.overlay.set_line_style(saved_style_value)
        else:
            default_style_enum = Qt.SolidLine
            default_index = self.style_combo.findData(default_style_enum)
            self.style_combo.setCurrentIndex(default_index if default_index !=-1 else 0)
            self.overlay.set_line_style(default_style_enum.value)

        self.arrow_size_spin.setValue(saved_arrow_size); self.overlay.set_arrow_head_size(saved_arrow_size)
        self.brush_size_spin.setValue(saved_brush_size); self.overlay.brush_size = saved_brush_size # Directly set overlay value
        self.fill_check.setChecked(saved_fill_state) # Set checkbox state
        self.dim_check.setChecked(saved_dimm_state); self.overlay.set_dim_background(saved_dimm_state)
        self.tool_text_check.setChecked(saved_tool_text_state); self.overlay.set_show_tool_text(saved_tool_text_state)

        # Unblock signals
        self.overlay.blockSignals(False)
        self.alpha_spin.blockSignals(False)
        self.thickness_spin.blockSignals(False)
        self.style_combo.blockSignals(False)
        self.arrow_size_spin.blockSignals(False)
        self.brush_size_spin.blockSignals(False)
        self.fill_check.blockSignals(False)
        self.dim_check.blockSignals(False)
        self.tool_text_check.blockSignals(False)

        # Update button styles that depend on restored values
        self.update_draw_color_button_style(restored_draw_color)
        self.update_edit_color_button_style(restored_edit_color)
        self.update_text_tool_button_style()


    def save_settings(self):
        """Save current settings to QSettings."""
        print("Saving control panel settings...")
        if not self.isMinimized(): self.settings.setValue("controlPanel/geometry", self.geometry()); print(f"Saved geometry: {self.geometry()}")
        else: print("Window minimized, skipping geometry save.")

        # --- Save Draw Mode Settings ---
        self.settings.setValue("controlPanel/drawPenColor", self.overlay.current_pen_color.name(QColor.HexArgb))
        self.settings.setValue("controlPanel/currentTool", self.overlay.current_tool)
        self.settings.setValue("controlPanel/alpha", self.overlay.current_alpha)
        self.settings.setValue("controlPanel/thickness", self.overlay.current_line_thickness)
        current_style_enum = self.style_combo.currentData()
        style_val_to_save = current_style_enum.value if isinstance(current_style_enum, Qt.PenStyle) else Qt.SolidLine.value
        self.settings.setValue("controlPanel/lineStyleValue", style_val_to_save)
        self.settings.setValue("controlPanel/arrowSize", self.overlay.current_arrow_head_size)
        self.settings.setValue("controlPanel/brushSize", self.overlay.brush_size)
        self.settings.setValue("controlPanel/fillChecked", self.fill_check.isChecked())
        self.settings.setValue("controlPanel/dimmChecked", self.dim_check.isChecked())
        self.settings.setValue("controlPanel/showToolText", self.tool_text_check.isChecked())

        # --- Save Default Text Properties (Normal Mode) ---
        if hasattr(self.overlay, 'default_text_properties'):
             defaults = self.overlay.default_text_properties
             self.settings.beginGroup("textDefaults")
             self.settings.setValue("font", defaults.get('font', 'Arial'))
             self.settings.setValue("size", defaults.get('size', 12))
             self.settings.setValue("bold", defaults.get('bold', False))
             self.settings.setValue("italic", defaults.get('italic', False))
             self.settings.setValue("underline", defaults.get('underline', False))
             self.settings.setValue("strikeout", defaults.get('strikeout', False))
             self.settings.setValue("color", defaults.get('color', '#000000'))
             self.settings.setValue("backgroundColor", defaults.get('background_color')) # Can be None
             self.settings.setValue("alignment", defaults.get('alignment', 'left'))
             self.settings.endGroup()
             print(f"Saved NORMAL default text properties: {defaults}")

        self.settings.sync(); print("Settings saved.")

    def adjust_position(self):
        """Adjust position near top-right (fallback)."""
        try:
             screen_geo = QGuiApplication.primaryScreen().availableGeometry()
             panel_width = self.width() if self.width() > 10 else self.sizeHint().width()
             panel_height = self.height() if self.height() > 10 else self.sizeHint().height()
             x = max(screen_geo.left(), screen_geo.right() - panel_width - 10)
             y = max(screen_geo.top(), screen_geo.top() + 10); y = min(y, screen_geo.bottom() - panel_height - 10)
             self.move(x, y); print("Control panel positioned near top-right (fallback).")
        except Exception as e: print(f"Error adjusting control panel position: {e}")

    def choose_draw_color(self):
        """Choose DRAW mode pen color (allows alpha)."""
        initial_color = self.overlay.current_pen_color
        color = QColorDialog.getColor(initial_color, self, "Choose Draw Color", QColorDialog.ShowAlphaChannel)
        if color.isValid():
            print(f"Setting DRAW Pen Color/Alpha via dialog: {color.name(QColor.HexArgb)}")
            # Set overlay color first, which might emit color_changed signal
            self.overlay.set_pen_color(color)
            # Update alpha slider and internal overlay alpha based on dialog selection
            self.alpha_spin.blockSignals(True)
            self.alpha_spin.setValue(color.alpha())
            self.alpha_spin.blockSignals(False)
            self.overlay.set_alpha(color.alpha()) # Update overlay's internal alpha
            self.update_draw_color_button_style(color) # Update button style

    def choose_edit_color(self):
        """Choose EDIT/BOARD mode pen color (no alpha)."""
        initial_color = self.overlay.current_pen_color_board
        color = QColorDialog.getColor(initial_color, self, "Choose Edit/Board Color")
        if color.isValid():
            print(f"Setting EDIT/BOARD Pen Color via dialog: {color.name(QColor.HexArgb)}")
            self.overlay.set_board_pen_color(color) # Updates indicator via update() and signals
            self.update_edit_color_button_style(color)

    @Slot(QColor)
    def update_draw_color_button_style(self, color):
        """Updates the 'Color Draw' button style."""
        if color.isValid():
            bg_color_css = color.name(QColor.HexRgb)
            text_color_css = 'white' if color.lightnessF() < 0.5 else 'black'
            self.draw_color_button.setStyleSheet(f"background-color: {bg_color_css}; color: {text_color_css};")
            self.draw_color_button.setToolTip(f"Draw Color: {color.name(QColor.HexArgb)}")
        else:
            self.draw_color_button.setStyleSheet("")
            self.draw_color_button.setToolTip("Invalid Draw Color")

    @Slot(QColor)
    def update_edit_color_button_style(self, color):
        """Updates the 'Color (Edit)' button style."""
        if color.isValid():
            bg_color_css = color.name(QColor.HexRgb)
            text_color_css = 'white' if color.lightnessF() < 0.5 else 'black'
            self.edit_color_button.setStyleSheet(f"background-color: {bg_color_css}; color: {text_color_css};")
            self.edit_color_button.setToolTip(f"Edit/Board Color: {color.name(QColor.HexRgb)}")
        else:
            self.edit_color_button.setStyleSheet("")
            self.edit_color_button.setToolTip("Invalid Edit/Board Color")

    @Slot(str)
    def set_tool(self, tool):
        """Sets the current drawing tool in the overlay and updates the radio button."""
        if tool not in self.tool_buttons: return
        if self.overlay.current_tool != tool:
             self.overlay.current_tool = tool; self.overlay.unsetCursor()
             self.overlay.current_drawing_shape = None; self.overlay.polygon_points.clear(); self.overlay.brush_points.clear()
             self.overlay.dragging = False; self.overlay.resizing = False; self.overlay.update()
             print(f"Control panel: Tool set to: {tool}")
        # Ensure the correct radio button is checked without emitting signals
        if not self.tool_buttons[tool].isChecked():
            self.tool_buttons[tool].blockSignals(True)
            self.tool_buttons[tool].setChecked(True)
            self.tool_buttons[tool].blockSignals(False)

    @Slot(int)
    def set_brush_size(self, size):
        """Updates the overlay's brush size."""
        size = max(1, size)
        if size != self.overlay.brush_size:
            self.overlay.brush_size = size
            print(f"Brush size set to: {self.overlay.brush_size}")

    @Slot(int)
    def on_style_combo_activated(self, index):
        """Handles selection change in the line style combobox."""
        style_enum = self.style_combo.itemData(index)
        if isinstance(style_enum, Qt.PenStyle): self.overlay.set_line_style(style_enum.value)

    @Slot(int)
    def update_fill_state(self, state):
        """Updates the overlay based on the fill checkbox state."""
        is_checked = (state == Qt.Checked)
        print(f"Fill checkbox state changed: {is_checked}")
        # Directly update selected shapes if desired (can be slow with many shapes)
        # if self.overlay.selected_shapes:
        #     needs_update = False
        #     for shape in self.overlay.selected_shapes:
        #         if shape.type in ['rect', 'ellipse', 'triangle', 'polygon']:
        #             if shape.filled != is_checked:
        #                 shape.filled = is_checked
        #                 needs_update = True
        #     if needs_update:
        #         self.overlay.update()

    @Slot()
    def update_controls_from_defaults(self):
        print("Updating control panel based on new NORMAL text defaults")
        self.update_text_tool_button_style()

    def update_text_tool_button_style(self):
        text_tool_btn = self.tool_buttons.get("text")
        if text_tool_btn: text_tool_btn.setStyleSheet("") # Clear specific style

    def save_scene_action(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save Scene", "", "JSON Files (*.json)")
        if filename: self.overlay.save_scene(filename)

    def load_scene_action(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Scene", "", "JSON Files (*.json)")
        if filename: self.overlay.save_state('load', all_shapes_before=deepcopy(self.overlay.shapes)); self.overlay.load_scene(filename, join=False)

    def load_and_join_scene_action(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load & Join Scene", "", "JSON Files (*.json)")
        if filename: self.overlay.save_state('load_join', shapes_involved=deepcopy(self.overlay.shapes)); self.overlay.load_scene(filename, join=True)

    def toggle_shortcuts_window(self, force_reset=False):
        """Toggles the shortcuts window. force_reset=True centers and maximizes height."""
        if self.shortcuts_window is None:
             self.shortcuts_window = ShortcutsWindow(self, self.settings)
             force_reset = True # Always reset on first open
             print("Shortcuts window created.")

        if not self.shortcuts_window.isVisible():
             if force_reset:
                 self.shortcuts_window.reset_and_center()
                 print("Shortcuts window reset and centered.")
             else:
                 # Try restoring geometry, fallback to reset/center
                 if not self.shortcuts_window.restore_geometry_from_settings():
                     self.shortcuts_window.reset_and_center()
                     print("Shortcuts window geometry restore failed, resetting.")
                 else:
                     print("Shortcuts window geometry restored.")

             self.shortcuts_window.show()
             self.shortcuts_window.activateWindow() # Bring to front
             print("Shortcuts window opened/shown.")
        else:
             # self.shortcuts_window.save_geometry_to_settings() # Save on hide - Handled by closeEvent now
             self.shortcuts_window.hide()
             print("Shortcuts window hidden.")

    def close_all(self):
        self.save_settings()
        if self.shortcuts_window and self.shortcuts_window.isVisible(): self.shortcuts_window.close() # Will trigger save geo
        self.close(); print("Control panel and shortcuts window closed")

    def closeEvent(self, event):
        print("ControlPanel closeEvent triggered.")
        self.save_settings()
        if self.shortcuts_window: self.shortcuts_window.close() # Will trigger save geo
        super().closeEvent(event)

    @Slot(bool)
    def handle_draw_mode_toggle(self, checked):
        # This is triggered by the user clicking the button
        self.overlay.set_drawing_mode(checked)
        # update_draw_button_style is called by update_draw_button_state via signal

    @Slot(bool)
    def update_draw_button_state(self, is_drawing):
        # This is triggered by the overlay changing state (e.g., via Alt+F1/F2/F3)
        # Prevent signal emission loop when updating button state programmatically
        self.drawing_button.blockSignals(True)
        self.drawing_button.setChecked(is_drawing)
        self.drawing_button.blockSignals(False)
        self.update_draw_button_style(is_drawing)

        # Note: Color buttons are updated in _configure_mode based on the final mode

    def update_draw_button_style(self, is_drawing):
        self.drawing_button.setStyleSheet(self.active_drawing_button_style if is_drawing else self.original_drawing_button_style)


# --- Klasa ShortcutsWindow ---
class ShortcutsWindow(QDialog):
    # Added settings argument
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.settings = settings # Store settings object
        self._first_show = True # Flag for initial centering
        self.setWindowTitle("Shortcuts")
        # Changed flags to allow normal window behavior (resize, minimize etc.)
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        layout = QVBoxLayout(self); layout.setSpacing(4); layout.setContentsMargins(8, 8, 8, 8)

        self.shortcuts_data = {
            "General": [
                ("Alt+F1", "Toggle Drawing Mode (Global Hotkey)"),
                ("Alt+F2", "Enter EDIT Mode (Global Hotkey)"),
                ("Alt+F3", "Enter BOARD Mode (Global Hotkey)"),
                ("Esc", "Exit Normal Draw Mode / Cancel Draw/Action"),
                ("Esc (x2 in BOARD/EDIT)", "Exit BOARD/EDIT mode (Confirm Clear)"), # Removed ask save
                ("Ctrl+Home", "Toggle Control Panel Visibility"),
                ("Ctrl+K", "Toggle This Shortcuts Window"), # Removed "(Reset Position)"
            ],
            "Tools": [
                ("R", "Rectangle"), ("E", "Ellipse"), ("T", "Triangle"), ("L", "Line Single"),
                ("A", "Arrow"), ("P", "Polygon (LMB=add, RMB/DblClk/Near Start=finish, Esc=cancel)"),
                ("M", "Line Point (LMB=add, RMB/DblClk=finish, Esc=cancel)"),
                ("B", "Brush"), ("X", "Text (Click/Drag = start pos/rect)"),
            ],
             "File & Scene": [
                ("Ctrl+S", "Save Scene"), ("Ctrl+L", "Load Scene (Replace)"),
                ("Load&Join Button", "Load Scene (Append)"), ("Shift+C", "Clear Scene"),
                ("EDIT Button / Alt+F2", "Enter Edit Mode (Transparent BG)"),
                ("BOARD Button / Alt+F3", "Enter Whiteboard Mode"),
            ],
            "Edit & Undo": [
                ("Ctrl+Z", "Undo"), ("Ctrl+Y / Ctrl+Shift+Z", "Redo"),
                ("Ctrl+C", "Copy Selected"), ("Ctrl+V", "Paste at Cursor"),
                ("Delete / Backspace", "Delete Selected"),
                ("Numpad '.' / Numpad Del", "Open Color Picker for Selected Shape(s)"), # Updated Numpad shortcut desc
                ("Double-Click Shape", "Delete Shape (non-Text)"),
                ("Double-Click Text", "Edit Text Properties"),
            ],
            "Selection & Manipulation": [
                ("LMB Click", "Select / Start Draw / Add Poly/Line Point"),
                ("Ctrl+LMB Click", "Add/Remove from Selection"),
                ("LMB Drag", "Draw / Move Selected / Resize (on handle)"),
                ("RMB Click", "Clear Selection / Finish Poly/Line Point"),
                ("Arrow Keys", "Nudge Selected (1px)"), ("Shift+Arrow Keys", "Nudge Selected (10px)"),
                ("+ / =", "Scale Up Selected"), ("Shift + + / =", "Scale Up (Larger)"),
                ("-", "Scale Down Selected"), ("Shift + -", "Scale Down (Larger)"),
                ("Ctrl+Left/Right", "Rotate Selected (90°)"), ("Alt+Left/Right", "Rotate Selected (1°) (Shows Angles)"),
                ("Shift+Drag (Draw)", "Constrain Proportions/Angle"),
                ("Shift+Drag (Resize)", "Maintain Aspect Ratio"),
            ],
            "Quick Properties (DRAW Mode Only - Hold key & LMB Click shape)": [
                 ("Ctrl+Alt+LMB Click", "Apply Current Draw Color"),
                 ("Ctrl+Alt+Shift+LMB Click", "Apply Current Draw Alpha"),
                 ("F + LMB Click", "Toggle Fill"),
            ],
             "Color Shortcuts (DRAW Mode Only - Press key)": [
                 ("0-9", "Apply Color (Selected or Current Draw Pen)"),
                 ("(See tooltips/docs for color mapping)", ""),
             ],
             "BOARD/EDIT Mode Only": [
                 ("0-9", "Apply Color (Selected Shape(s) or Current Edit Pen)"),
                 ("Alt + 0-9", "Change BOARD Background Color (RGB, preserves Alpha)"),
                 ("Ctrl + 0-9", "Change BOARD Background Transparency (0=Min Alpha(1), 9=Opaque)"),
                 ("(See tooltips/docs for color mapping)", ""),
             ]
        }

        self.table_widget = QTableWidget(); self.table_widget.setColumnCount(2); self.table_widget.setHorizontalHeaderLabels(["Shortcut", "Description"])
        self.table_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_widget.verticalHeader().setVisible(False); self.table_widget.setShowGrid(True); self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setStyleSheet("QTableWidget { gridline-color: #888888; outline: 1px solid #666666; border: 1px solid #a0a0a0; } QTableWidget::item { padding: 4px; border-bottom: 1px solid #c0c0c0; border-right: 1px solid #c0c0c0; } QTableWidget QHeaderView::section { background-color: #e0e0e0; padding: 4px; border: 1px solid #b0b0b0; border-bottom: 2px solid #909090; } QTableWidget::item:hover { background-color: #e8f0fe; }")

        row = 0
        for section, shortcuts in self.shortcuts_data.items():
            section_item = QTableWidgetItem(f"--- {section} ---"); section_item.setTextAlignment(Qt.AlignCenter); f = section_item.font(); f.setBold(True); section_item.setFont(f); section_item.setBackground(QColor("#f0f0f0"))
            self.table_widget.insertRow(row); self.table_widget.setItem(row, 0, section_item); self.table_widget.setSpan(row, 0, 1, 2); row += 1
            for key, desc in shortcuts:
                self.table_widget.insertRow(row); key_item = QTableWidgetItem(key); desc_item = QTableWidgetItem(desc); f = key_item.font(); f.setBold(True); key_item.setFont(f)
                self.table_widget.setItem(row, 0, key_item); self.table_widget.setItem(row, 1, desc_item); row += 1
            # Add visual spacer row unless it's the very last section
            if section != list(self.shortcuts_data.keys())[-1]:
                 self.table_widget.insertRow(row); self.table_widget.setSpan(row, 0, 1, 2); self.table_widget.setRowHeight(row, 1)
                 spacer_item = QTableWidgetItem(""); spacer_item.setBackground(self.palette().color(QPalette.ColorRole.Base)); self.table_widget.setItem(row, 0, spacer_item); row += 1


        self.table_widget.resizeColumnsToContents(); self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        scrollbar_width = self.table_widget.verticalScrollBar().sizeHint().width() if self.table_widget.verticalScrollBar().isVisible() else 0
        # Calculate width more reliably
        width_hint = self.table_widget.horizontalHeader().length() + self.table_widget.verticalHeader().width() + self.table_widget.frameWidth() * 2 + scrollbar_width + 15 # Add margin
        self.setMinimumWidth(max(550, width_hint))
        layout.addWidget(self.table_widget)

        button_layout = QHBoxLayout()
        export_button = QPushButton("Export to File"); export_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed); export_button.clicked.connect(self.export_shortcuts); button_layout.addWidget(export_button)
        print_button = QPushButton("Print"); print_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        if not _QT_PRINT_SUPPORT_AVAILABLE: print_button.setEnabled(False); print_button.setToolTip("Printing requires QtPrintSupport")
        else: print_button.clicked.connect(self.print_shortcuts)
        button_layout.addWidget(print_button); button_layout.addStretch()
        close_button = QPushButton("Close"); close_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed); close_button.clicked.connect(self.close); button_layout.addWidget(close_button)
        layout.addLayout(button_layout)

        # Initial size/pos setting removed, handled by reset_and_center or restore_geometry_from_settings

    def reset_and_center(self):
        """Resizes to max screen height and centers the window."""
        try:
            screen_geo = QGuiApplication.primaryScreen().availableGeometry()
            max_height = screen_geo.height() - 40 # Allow some margin
            # Use minimum width calculated earlier
            target_width = self.minimumWidth()
            self.resize(target_width, max_height)

            # Center on screen
            x = screen_geo.left() + (screen_geo.width() - target_width) // 2
            y = screen_geo.top() + (screen_geo.height() - max_height) // 2
            self.move(max(screen_geo.left(), x), max(screen_geo.top(), y)) # Ensure it's on screen
            print(f"Shortcuts window reset to max height ({max_height}px) and centered.")
        except Exception as e:
            print(f"Error resetting/centering shortcuts window: {e}")
            self.resize(600, 800) # Fallback size

    def restore_geometry_from_settings(self):
        """Loads geometry from settings and applies it, returns True if successful."""
        if self.settings:
            geom_bytes = self.settings.value("shortcutsWindow/geometry")
            if geom_bytes and isinstance(geom_bytes, (bytes, bytearray)):
                if self.restoreGeometry(geom_bytes):
                    # Ensure it's on screen after restoring
                    screen_geo = QGuiApplication.primaryScreen().availableGeometry()
                    window_geo = self.geometry()
                    if not screen_geo.intersects(window_geo.adjusted(-5, -5, 5, 5)):
                        print("Restored shortcuts window geometry off-screen, resetting.")
                        return False # Indicate failure -> leads to reset
                    print(f"Restored shortcuts window geometry: {self.geometry()}")
                    return True
                else:
                    print("Failed to restore shortcuts window geometry from bytes.")
            else:
                print("No valid shortcuts window geometry found in settings.")
        return False

    def save_geometry_to_settings(self):
        """Saves the current window geometry to settings."""
        if self.settings and not self.isMinimized():
            geom_bytes = self.saveGeometry()
            self.settings.setValue("shortcutsWindow/geometry", geom_bytes)
            print(f"Saved shortcuts window geometry: {self.geometry()}")

    def closeEvent(self, event):
        """Save geometry when the window is closed."""
        print("ShortcutsWindow closeEvent triggered.")
        self.save_geometry_to_settings()
        super().closeEvent(event)

    def get_shortcuts_html(self):
        html = """<!DOCTYPE html><html><head><style>table { border-collapse: collapse; width: 100%; font-family: sans-serif; font-size: 10pt; border: 1px solid #666; } th, td { border: 1px solid #a0a0a0; padding: 4px; text-align: left; vertical-align: top; } th { background-color: #e0e0e0; font-weight: bold; border-bottom: 2px solid #666; } .section-header td { font-weight: bold; text-align: center; background-color: #f0f0f0; border-top: 2px solid #666; border-bottom: 1px solid #aaa; } .shortcut-key { font-weight: bold; }</style></head><body><h2>Keyboard Shortcuts</h2><table><thead><tr><th>Shortcut</th><th>Description</th></tr></thead><tbody>"""
        first_section = True
        for section, shortcuts in self.shortcuts_data.items():
            style_attr = "" if first_section else ' style="border-top: 2px solid #666;"'
            html += f'<tr class="section-header"><td colspan="2"{style_attr}>--- {section} ---</td></tr>\n'; first_section = False
            for key, desc in shortcuts: html += f'<tr><td class="shortcut-key">{key}</td><td>{desc}</td></tr>\n'
        html += "</tbody></table></body></html>"
        return html

    def get_shortcuts_text(self):
        lines = []
        for section, shortcuts in self.shortcuts_data.items():
            lines.append(f"--- {section} ---"); lines.append("")
            for key, desc in shortcuts: lines.append(f"{key:<25}: {desc}")
            lines.append("-" * 40); lines.append("")
        return "\n".join(lines)

    @Slot()
    def export_shortcuts(self):
        text_content = self.get_shortcuts_text()
        filename, _ = QFileDialog.getSaveFileName(self, "Export Shortcuts As", "", "Text Files (*.txt)")
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f: f.write(text_content); print(f"Shortcuts exported to {filename}")
            except IOError as e: QMessageBox.warning(self, "Export Error", f"Could not save file:\n{e}")

    @Slot()
    def print_shortcuts(self):
        if not _QT_PRINT_SUPPORT_AVAILABLE: QMessageBox.warning(self, "Printing Unavailable", "QtPrintSupport not found."); return
        html_content = self.get_shortcuts_html(); doc = QTextDocument(); doc.setHtml(html_content)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution); dialog = QPrintDialog(printer, self); dialog.setWindowTitle("Print Shortcuts")
        if dialog.exec() == QDialog.DialogCode.Accepted: # Use DialogCode enum
            try: doc.print_(printer); print("Shortcuts sent to printer.")
            except Exception as e: QMessageBox.warning(self, "Print Error", f"Could not print:\n{e}")
        else: print("Printing cancelled.")


# --- Main Application Setup ---
class MainApplication(QApplication):
     def __init__(self, args):
          super().__init__(args)
          self.setOrganizationName("MyCompany"); self.setApplicationName("DesktopOverlayRGN")
          self.overlay = DesktopOverlayRgn()
          self.control_panel = ControlPanel(self.overlay)
          self.overlay.defaults_changed.connect(self.control_panel.update_controls_from_defaults)
          self.control_panel.show()
          # Overlay is shown during its initialization (_get_hwnd)

     def exec(self):
         print("Starting application event loop...")
         result = super().exec()
         try:
             # Ensure settings are saved when the application exits cleanly
             if self.control_panel: self.control_panel.save_settings()
             # Save board settings if desired on exit (now saved automatically on board mode exit)
             if self.overlay and self.overlay.board_mode:
                 print("MainApplication: Saving BOARD settings on exit as it was active.")
                 self.overlay.save_board_settings()
             print("MainApplication: Settings potentially saved on exit.")
         except Exception as e: print(f"MainApplication: Error saving settings on exit: {e}")
         finally:
             # Ensure hotkey is unregistered even if saving fails or overlay close failed
             try:
                 if self.overlay:
                     # Call unregister directly if the overlay might still exist
                     self.overlay._unregister_global_hotkey()
                     print("MainApplication: Attempted hotkey unregistration on exit.")
             except Exception as e: print(f"MainApplication: Error unregistering hotkey on exit: {e}")
         print(f"Application event loop finished with result code: {result}")
         return result

def handle_global_hotkey(hotkey_id, overlay):
    if hotkey_id == 1:
        print("Alt+F1 triggered → toggling drawing mode")
        overlay.set_drawing_mode(not overlay.drawing_mode)
    elif hotkey_id == 2:
        print("Alt+F2 triggered → entering EDIT mode")
        overlay.enter_edit_mode()
    elif hotkey_id == 3:
        print("Alt+F3 triggered → entering BOARD mode")
        overlay.enter_board_mode()
    else:
        print(f"Unhandled hotkey ID: {hotkey_id}")


# --- Główna funkcja ---
if __name__ == "__main__":
    # Qt High DPI Scaling Attributes
    if hasattr(Qt, 'AA_EnableHighDpiScaling'): QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'): QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # Set HighDpiScaleFactorRoundingPolicy if available (Qt >= 5.14)
    if hasattr(Qt, 'HighDpiScaleFactorRoundingPolicy') and hasattr(QApplication, 'setHighDpiScaleFactorRoundingPolicy'):
        try:
            # Use PassThrough for potentially sharper results on fractional scaling
            QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
            print("Set HighDpiScaleFactorRoundingPolicy to PassThrough")
        except AttributeError:
            print("Warning: Could not set HighDpiScaleFactorRoundingPolicy (might be older Qt version)")
        except Exception as e:
            print(f"Warning: Error setting HighDpiScaleFactorRoundingPolicy: {e}")

    app = MainApplication(sys.argv)
        

    overlay = DesktopOverlayRgn()

    # Zainstaluj filtr globalnych hotkeyów
    filter = GlobalHotkeyFilter(lambda hotkey_id: handle_global_hotkey(hotkey_id, overlay))
    app.installNativeEventFilter(filter)

    # Pokaż okno i uruchom aplikację
    overlay.show()
    sys.exit(app.exec())
    


# <<< END OF MODIFIED FILE grok36_mod.py >>>