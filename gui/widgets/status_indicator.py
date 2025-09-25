from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer


def create_status_indicator(loaded: bool) -> QPixmap:
    """Creates a PIXMAP SVG for the status indicator"""
    # SVG pour statut chargé (vert)
    loaded_svg = """
    <svg width="20" height="20" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="9" fill="#2ecc72" stroke="#27ae60" stroke-width="1.5"/>
        <circle cx="10" cy="10" r="7" fill="none" stroke="#88ff88" stroke-width="3" opacity="0.8"/>
    </svg>
    """

    # SVG pour statut non chargé (rouge)
    unloaded_svg = """
    <svg width="20" height="20" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="9" fill="#e74c3d" stroke="#92251b" stroke-width="1.5"/>
        <circle cx="10" cy="10" r="7" fill="none" stroke="#ec725c" stroke-width="3" opacity="0.8"/>
    </svg>
    """

    svg_data = loaded_svg if loaded else unloaded_svg
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(QByteArray(svg_data.encode()))
    if renderer.isValid():
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)  # Lissage
        renderer.render(painter)
        painter.end()

    return pixmap
