from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class TooManyFilesError(RuntimeError):
    """Exception lifted by Contextparser when exceeding the limit."""

    pass


class AnalyzeWorker(QObject):
    """Worker executed in a Qthread, without any dependence on the panel."""

    finished = pyqtSignal(list)  # list[Path] → envoyé quand le scan a réussi
    error = pyqtSignal(str)  # message d'erreur (incl. TooManyFilesError)

    def __init__(self, parser=None, root: Path = None, forced_limit: bool = False):
        """
        *parser*  : instance of ContextParser (injected from the panel)
        *root*    : folder to scan
        """
        super().__init__()
        self.parser = parser
        self.root = root
        self.forced_limit = forced_limit

    @pyqtSlot()
    def run(self) -> None:
        """Method called by Qthread with potential heavy work."""
        try:
            files = self.parser.list_files(self.root, raise_on_limit=not self.forced_limit)
            self.finished.emit(files)
        except TooManyFilesError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))
