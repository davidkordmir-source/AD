"""Local OSM boundary map: no tiles, web view, sockets or remote requests."""
import gzip
import json
import math
from pathlib import Path

import numpy as np
from osgeo import gdal
from PySide6 import QtCore, QtGui, QtWidgets


MAP_LIMIT = 20037508.342789244


def application_asset(name):
    for base in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
        candidate = base/"assets"/name
        if candidate.is_file():
            return candidate
    return None


def mercator_point(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    return QtCore.QPointF(lon*MAP_LIMIT/180, -6378137*math.log(math.tan(math.pi/4+math.radians(lat)/2)))


from desktop_customization import load_map_file
from professional_ui import ProfessionalMapMixin

class _BoundaryMapBase(QtWidgets.QGraphicsView):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QtGui.QColor('#eaf2f6'))
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setMinimumSize(300, 300)
        self.boundary_count = 0
        self.background_items = []
        self.custom_bounds = None
        self.map_style = {}
        self.observers = []
        self.point_items = []
        self.overlays = {}
        self.active_fid = None
        self.result_cache = {}
        self.visible_only = True
        self.initial_fit = True
        self._load_boundaries()
        self.scene().setSceneRect(-MAP_LIMIT, -MAP_LIMIT, 2 * MAP_LIMIT, 2 * MAP_LIMIT)
        self.fit_world()

    def _load_boundaries(self):
        default = application_asset('default_map/area.shp')
        if default:
            data = load_map_file(default)
            points = application_asset('default_map/point.shp')
            if points:
                labels = load_map_file(points)
                data['paths'].extend(labels['paths'])
                data['count'] += labels['count']
                data['bounds'] = data['bounds'].united(labels['bounds'])
            self.replace_background(data)
            return
        path = application_asset('osm_countries.geojson.gz')
        if path is None:
            return
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            data = json.load(stream)
        pen = QtGui.QPen(QtGui.QColor('#7c97a6'), 1.05)
        pen.setCosmetic(True)
        for feature in data['features']:
            geometry = feature['geometry']
            polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
            painter_path = QtGui.QPainterPath()
            painter_path.setFillRule(QtCore.Qt.OddEvenFill)
            for polygon in polygons:
                for ring in polygon:
                    previous = None
                    for lon, lat, *_ in ring:
                        point = mercator_point(lon, lat)
                        if previous is None or abs(lon - previous) > 180:
                            painter_path.moveTo(point)
                        else:
                            painter_path.lineTo(point)
                        previous = lon
            item = self.scene().addPath(painter_path, pen, QtGui.QBrush(QtGui.QColor('#fafcfd')))
            item.setZValue(-10)
            item.setToolTip(feature['properties'].get('name', ''))
            self.boundary_count += 1
            self.background_items.append(item)

    def fit_world(self):
        if self.custom_bounds is not None:
            rect = self.custom_bounds
            padding = max(rect.width(), rect.height(), 1000) * 0.04
            self.fitInView(rect.adjusted(-padding, -padding, padding, padding), QtCore.Qt.KeepAspectRatio)
            self.initial_fit = True
            self.update_map_details()
            return
        self.fitInView(QtCore.QRectF(-MAP_LIMIT, -MAP_LIMIT * 0.65, 2 * MAP_LIMIT, MAP_LIMIT * 1.3), QtCore.Qt.KeepAspectRatio)
        self.initial_fit = True
        self.update_map_details()

    def update_map_details(self):
        detailed = abs(self.transform().m11()) >= 1 / 20000
        for item in self.background_items:
            if item.data(0) == 'backgroundPoint':
                item.setVisible(detailed)

    def zoom_by(self, factor):
        self.scale(factor, factor)
        self.initial_fit = False
        self.update_map_details()

    def apply_map_style(self, ui):
        self.map_style = ui
        self.setBackgroundBrush(QtGui.QColor(ui['map_background']))
        pen = QtGui.QPen(QtGui.QColor(ui['map_line']), 1.05)
        pen.setCosmetic(True)
        for item in self.background_items:
            if isinstance(item, QtWidgets.QGraphicsPathItem):
                item.setPen(pen)
                if item.data(0) != 'line':
                    item.setBrush(QtGui.QBrush(QtGui.QColor(ui['map_fill'])))

    def replace_background(self, data):
        new_items = []
        try:
            if data['kind'] == 'raster':
                item = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap.fromImage(data['image']))
                gt = data['transform']
                item.setTransform(QtGui.QTransform(gt[1], 0, 0, -gt[5], gt[0], -gt[3]))
                new_items.append(item)
            else:
                for kind, geometry, label in data['paths']:
                    if kind == 'point':
                        item = QtWidgets.QGraphicsEllipseItem(-1.5, -1.5, 3, 3)
                        item.setData(0, 'backgroundPoint')
                        item.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
                        item.setPos(*geometry)
                        item.setPen(QtGui.QPen(QtGui.QColor('#526f80')))
                        item.setBrush(QtGui.QBrush(QtGui.QColor('#526f80')))
                    else:
                        item = QtWidgets.QGraphicsPathItem(geometry)
                        item.setData(0, kind)
                    item.setToolTip(label)
                    new_items.append(item)
            for item in new_items:
                item.setZValue(-10)
                self.scene().addItem(item)
        except Exception:
            for item in new_items:
                if item.scene() is self.scene():
                    self.scene().removeItem(item)
            raise
        for item in self.background_items:
            self.scene().removeItem(item)
        self.background_items = new_items
        self.custom_bounds = data['bounds']
        self.boundary_count = data['count']
        self.scene().setSceneRect(self.scene().sceneRect().united(data['bounds']))
        self.apply_map_style(self.map_style or dict(map_line='#7c97a6', map_fill='#fafcfd', map_background='#eaf2f6'))
        self.fit_world()

    def restore_default_background(self):
        for item in self.background_items:
            self.scene().removeItem(item)
        self.background_items = []
        self.boundary_count = 0
        self.custom_bounds = None
        self._load_boundaries()
        if self.map_style:
            self.apply_map_style(self.map_style)
        self.fit_world()

    def set_observers(self, observers, radius=100000):
        for item in self.point_items:
            self.scene().removeItem(item)
        self.point_items = []
        self.observers = observers
        self.clear_results()
        for fid, lon, lat in observers:
            position = mercator_point(lon, lat)
            item = QtWidgets.QGraphicsEllipseItem(-5, -5, 10, 10)
            item.setPen(QtGui.QPen(QtGui.QColor('white'), 2))
            item.setBrush(QtGui.QBrush(QtGui.QColor('#145e78')))
            item.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
            item.setPos(position)
            item.setZValue(20)
            item.setToolTip(f'FID={fid} | {lon:.5f}, {lat:.5f}')
            self.scene().addItem(item)
            self.point_items.append(item)
        self.fit_observers(radius)

    def fit_observers(self, radius=100000):
        if not self.observers:
            self.fit_world()
            return
        positions = [mercator_point(lon, lat) for _, lon, lat in self.observers]
        xs, ys = ([p.x() for p in positions], [p.y() for p in positions])
        padding = max(200000, radius * 2.5)
        bounds = QtCore.QRectF(min(xs) - padding, min(ys) - padding, max(xs) - min(xs) + 2 * padding, max(ys) - min(ys) + 2 * padding)
        self.fitInView(bounds, QtCore.Qt.KeepAspectRatio)
        self.initial_fit = False
        self.update_map_details()

    def clear_results(self):
        for item in self.overlays.values():
            self.scene().removeItem(item)
        self.overlays = {}
        self.result_cache = {}
        self.active_fid = None

    def set_visible_only(self, flag):
        if self.visible_only == flag:
            return
        self.visible_only = flag
        for fid, (classes, metadata) in list(self.result_cache.items()):
            self.add_result(fid, classes, metadata, flag, cache=False)

    def add_result(self, fid, classes, metadata, visible_only=True, cache=True):
        if 'transform' not in metadata or 'crs' not in metadata:
            return
        stride = max(1, (max(classes.shape) + 799) // 800)
        small = np.ascontiguousarray(classes[::stride, ::stride])
        transform = list(metadata['transform'])
        transform[0] += (1 - stride) * transform[1] / 2
        transform[3] += (1 - stride) * transform[5] / 2
        transform[1] *= stride
        transform[5] *= stride
        if cache:
            self.result_cache[fid] = (small.copy(), {**metadata, 'transform': transform})
        self.visible_only = visible_only
        source = gdal.GetDriverByName('MEM').Create('', small.shape[1], small.shape[0], 1, gdal.GDT_Byte)
        source.SetProjection(metadata['crs'])
        source.SetGeoTransform(transform)
        source.GetRasterBand(1).SetNoDataValue(255)
        source.GetRasterBand(1).WriteArray(small)
        warped = gdal.Warp('', source, format='MEM', dstSRS='EPSG:3857', resampleAlg='near', width=700, dstNodata=255, multithread=False)
        array = warped.GetRasterBand(1).ReadAsArray()
        rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
        rgba[array == 1] = (213, 45, 70, 205)
        if not visible_only:
            rgba[array == 1] = (42, 184, 111, 190)
            rgba[array == 0] = (221, 72, 77, 170)
            rgba[array == 2] = (143, 151, 158, 130)
        height, width = array.shape
        image = QtGui.QImage(rgba.data, width, height, width * 4, QtGui.QImage.Format_RGBA8888).copy()
        item = QtWidgets.QGraphicsPixmapItem(QtGui.QPixmap.fromImage(image))
        gt = warped.GetGeoTransform()
        item.setTransform(QtGui.QTransform(gt[1], 0, 0, -gt[5], gt[0], -gt[3]))
        item.setZValue(5)
        item.setToolTip(f"FID={fid} — {metadata.get('name', '')}")
        if fid in self.overlays:
            self.scene().removeItem(self.overlays[fid])
        self.scene().addItem(item)
        self.overlays[fid] = item
        source = warped = None

    def highlight(self, fid):
        self.active_fid = fid
        for key, item in self.overlays.items():
            item.setOpacity(1 if key == fid else 0.45)

    def wheelEvent(self, event):
        delta = event.pixelDelta().y() or event.angleDelta().y()
        if delta:
            factor = 1.18 if delta > 0 else 1 / 1.18
            scale = abs(self.transform().m11())
            if 1e-07 < scale * factor < 10:
                self.zoom_by(factor)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.initial_fit:
            self.fit_world()

class OfflineBoundaryMap(ProfessionalMapMixin, _BoundaryMapBase):
    pass
