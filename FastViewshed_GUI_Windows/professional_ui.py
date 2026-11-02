"""Shared desktop palette and readable map annotations; no network resources."""
import hashlib
from PySide6 import QtCore, QtGui, QtWidgets

MAP_DEFAULTS = dict(accent='#20b8d6', map_line='#477d96', map_fill='#1b3b52',
                    map_background='#0b1c2c')
STYLE = '''
QWidget {font-family:"Segoe UI","Tahoma";font-size:12px;color:#deedf7;}
QMainWindow,QDialog {background:#0b1524;}
QWidget#formPanel,QScrollArea,QScrollArea>QWidget>QWidget {background:#0b1524;}
QLabel {background:transparent;}
QLabel#title {font-size:25px;font-weight:800;color:#f4fbff;padding:6px 0;}
QGroupBox {font-weight:600;border:1px solid #29455c;border-radius:12px;margin-top:17px;
 padding:19px 10px 10px;background:#12263a;}
QGroupBox::title {subcontrol-origin:margin;padding:2px 9px;color:#a9e9ff;}
QGroupBox[priority="true"] {border-width:2px;font-size:14px;font-weight:800;}
QGroupBox#inputSection {border-color:#358cdb;background:#102b45;}
QGroupBox#dimensionSection {border-color:#22b8b0;background:#103236;}
QGroupBox#outputSection {border-color:#9980ef;background:#28233f;}
QGroupBox#inputSection::title {color:#a5d7ff;background:#173b5c;border-radius:5px;}
QGroupBox#dimensionSection::title {color:#8ff3db;background:#174440;border-radius:5px;}
QGroupBox#outputSection::title {color:#d9c8ff;background:#3b315a;border-radius:5px;}
QLineEdit,QComboBox,QDoubleSpinBox,QSpinBox {padding:8px;border:1px solid #416079;
 border-radius:7px;background:#0c1e30;selection-background-color:#147cb0;color:#f3faff;}
QLineEdit:focus,QComboBox:focus,QDoubleSpinBox:focus,QSpinBox:focus {border:2px solid #2bc6e2;}
QComboBox QAbstractItemView {background:#122d43;color:#f1f8ff;selection-background-color:#176b93;}
QPushButton {padding:9px 13px;border:1px solid #436680;border-radius:8px;background:#1a3b54;font-weight:600;}
QPushButton:hover {background:#235775;border-color:#47c4e0;}
QPushButton:pressed {background:#117d9e;}
QPushButton#run {background:#20b8d6;color:#041824;font-weight:800;border-color:#75e3ed;}
QPushButton#run:hover {background:#5cdaeb;}
QPushButton:disabled {color:#73899c;background:#1b2a3a;border-color:#2c4052;}
QCheckBox,QRadioButton {spacing:7px;padding:3px;}
QCheckBox::indicator {width:17px;height:17px;border:1px solid #678ca5;border-radius:4px;background:#0b2033;}
QCheckBox::indicator:checked {background:#20b8d6;border:3px solid #a0eff7;}
QRadioButton::indicator:checked {background:#20b8d6;}
QTabWidget::pane {border:1px solid #36556c;border-radius:9px;background:#102338;}
QTabBar::tab {background:#122b40;color:#b2cbdd;padding:10px 16px;border-radius:6px;margin:2px;}
QTabBar::tab:selected {background:#1d617e;color:#ffffff;border-bottom:3px solid #2cd6db;}
QScrollBar:vertical {background:#102338;width:15px;border-radius:7px;margin:0;}
QScrollBar::handle:vertical {background:#426e89;min-height:38px;border-radius:7px;}
QScrollBar::handle:vertical:hover {background:#2fc1d7;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QLabel#mapAttribution {font-size:10px;color:#9abbd0;padding:5px;}
QGraphicsView {border:1px solid #375d76;border-radius:9px;background:#0b1c2c;}
QProgressBar {border:1px solid #406179;border-radius:6px;text-align:center;height:19px;background:#0a1a2a;}
QProgressBar::chunk {background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #348de1,stop:1 #23d2b1);border-radius:5px;}
QPlainTextEdit {background:#081420;color:#c9edf5;font-family:Consolas;border:1px solid #36556c;border-radius:8px;}
QToolTip {color:#f0f8ff;background:#1a3c54;border:1px solid #65cce0;padding:5px;}
'''


class ProfessionalMapMixin:
    """Screen-space labels stay readable on zoom and do not cover each other."""
    def replace_background(self, data):
        super().replace_background(data)
        best = {}
        for label in data.get('labels', []):
            text = label['text'].strip()
            if text and (text not in best or label['priority'] > best[text]['priority']):
                best[text] = label
        self.country_labels = sorted(best.values(), key=lambda x: x['priority'], reverse=True)
        self.labels_visible = getattr(self, 'labels_visible', True)
        self.viewport().update()

    def apply_map_style(self, ui):
        super().apply_map_style(ui)
        base = QtGui.QColor(ui.get('map_fill', MAP_DEFAULTS['map_fill']))
        for item in self.background_items:
            if isinstance(item, QtWidgets.QGraphicsPathItem) and item.data(0) != 'line':
                shade = hashlib.sha256(item.toolTip().encode('utf-8')).digest()[0]
                item.setBrush(QtGui.QBrush(base.lighter(92 + shade % 32)))
        self.viewport().update()

    def set_observers(self, observers, radius=100000):
        super().set_observers(observers, radius)
        for item in self.point_items:
            item.setRect(-7, -7, 14, 14)
            item.setBrush(QtGui.QBrush(QtGui.QColor('#ff304d')))
            item.setPen(QtGui.QPen(QtGui.QColor('#ffffff'), 2.3))
            halo = QtWidgets.QGraphicsEllipseItem(-11, -11, 22, 22, item)
            halo.setPen(QtGui.QPen(QtGui.QColor('#ff304d'), 2))
            halo.setBrush(QtGui.QColor(255, 48, 77, 45))
            halo.setZValue(-1)
        self.viewport().update()

    def update_map_details(self):
        super().update_map_details()
        self.viewport().update()

    def set_labels_visible(self, visible):
        self.labels_visible = visible
        self.viewport().update()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        self.visible_country_labels = []
        if not getattr(self, 'labels_visible', True):
            return
        painter.save()
        painter.resetTransform()
        font = QtGui.QFont('Segoe UI', 9)
        font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(font)
        metrics = QtGui.QFontMetricsF(font)
        viewport = self.viewport().rect().adjusted(3, 3, -3, -3)
        occupied = [QtCore.QRectF(self.mapFromScene(item.pos()).x()-14,
                                self.mapFromScene(item.pos()).y()-14, 28, 28)
                    for item in self.point_items]
        buckets = {}
        for candidate in getattr(self, 'country_labels', []):
            point = self.mapFromScene(QtCore.QPointF(*candidate['position']))
            if not viewport.contains(point):
                continue
            text = metrics.elidedText(candidate['text'], QtCore.Qt.ElideRight, 170)
            box = QtCore.QRectF(point.x()-metrics.horizontalAdvance(text)/2-5,
                                point.y()-metrics.height()/2-3,
                                metrics.horizontalAdvance(text)+10, metrics.height()+6)
            cells = [(x, y) for x in range(int(box.left()//80), int(box.right()//80)+1)
                     for y in range(int(box.top()//30), int(box.bottom()//30)+1)]
            if not QtCore.QRectF(viewport).contains(box) or any(box.intersects(r) for r in occupied):
                continue
            if any(box.intersects(r) for cell in cells for r in buckets.get(cell, [])):
                continue
            for cell in cells:
                buckets.setdefault(cell, []).append(box.adjusted(-2, -2, 2, 2))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(5, 18, 31, 200))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QtGui.QColor('#eefaff'))
            painter.drawText(box, QtCore.Qt.AlignCenter, text)
            self.visible_country_labels.append((candidate['text'], box))
        painter.restore()
