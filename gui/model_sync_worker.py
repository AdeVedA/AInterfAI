from PyQt6.QtCore import QThread, pyqtSignal


class ModelSyncWorker(QThread):
    """
    Runs LLMPropertiesManager.sync_missing_and_refresh() in a background QThread.
    Emits signals so the UI can show progress and eventually present a diff dialog.
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(list)

    def __init__(self, props_mgr, force_refresh: bool = False):
        super().__init__()
        self.props_mgr = props_mgr
        self.force_refresh = force_refresh

    def run(self) -> None:
        try:
            diffs = self.props_mgr.sync_missing_and_refresh(
                force_refresh=self.force_refresh,
                progress_callback=lambda txt: self.progress.emit(txt),
            )
            # print("diff avant émission : ", diffs)
            self.finished.emit(diffs)  # liste de dicos
        except Exception as exc:
            print("Exception in the ModelSyncWorker : ")
            print(f"Error: {exc}")
            self.finished.emit([])
