# Le signal rendered(html, index) est envoyé quand la conversion est finie.
# index est un entier utilisé pour savoir dans quelle bulle (quel message de la sesison) on doit injecter le HTML.
# Le signal error(msg, index) permet de capturer d'éventuelles exceptions dans la conversion.

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from core.renderer import MarkdownRenderer


class RendererWorker(QObject):
    """
    Worker Qt executed in a QThread to do the conversion Markdown -> HTML
    ouside of the thread GUI.
    """

    rendered = pyqtSignal(str, int)  # émet (html_str, message_index)
    error = pyqtSignal(str, int)  # si une erreur survient : (message d'erreur, index)
    css_ready = pyqtSignal(str)  # signal pour notifier le CSS

    def __init__(self, theme_manager=None):
        super().__init__()
        self.theme_manager = theme_manager
        self._renderer = MarkdownRenderer(theme_manager=self.theme_manager)

    @pyqtSlot(str, int)
    def process(self, markdown_text: str, index: int):
        """
        Slot called from the main thread. Makes a background conversion,
        Then emits `rendered(html, index)` when finished.
        """
        try:
            html = self._renderer.render(markdown_text)
            # print("html :\n", html)
            self.rendered.emit(html, index)
        except Exception as e:
            self.error.emit(str(e), index)

    @pyqtSlot()
    @pyqtSlot(str)
    def send_current_css(self, *args):
        """Emit the current themed CSS (called with or without theme_name)."""
        # print("DEBUG: RendererWorker.send_current_css called, args =", args)
        try:
            css = self._renderer.themed_stylesheet()
        except Exception as e:
            print("ERROR: RendererWorker.themed_stylesheet failed:", e)
            css = ""
        self.css_ready.emit(css)
