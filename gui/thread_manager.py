import threading

from PyQt6 import sip
from PyQt6.QtCore import QThread


class ThreadManager:
    """
    Centralized manager for both QThread (Qt) and threading.Thread (Python).
    Responsibilities:
    - Keep references to all running threads (so they are not garbage-collected too early).
    - Ensure a clean shutdown of all registered threads when the application exits.
    - Provide convenience methods for starting and registering threads.
    Usage:
        manager = ThreadManager()
        # For QThread
        thread = QThread()
        worker = MyWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        manager.start_qthread(thread)
        # For threading.Thread
        t = threading.Thread(target=some_function)
        manager.start_thread(t)
        # On application exit (MainWindow):
        manager.shutdown()
    """

    def __init__(self):
        self.qthreads: list[QThread] = []
        self.threads: list[threading.Thread] = []

    # QThread management
    def register_qthread(self, thread: QThread):
        """
        Register an existing QThread for later shutdown.
        To use if we manually start() the thread.
        """
        if thread not in self.qthreads:
            self.qthreads.append(thread)

    def start_qthread(self, thread: QThread):
        """
        Register and start a QThread in one step.
        Useful if we don't need to delay the start.
        """
        self.register_qthread(thread)
        thread.finished.connect(lambda: self.unregister_qthread(thread))
        thread.start()

    def unregister_qthread(self, thread: QThread) -> None:
        """Remove a QThread from the internal list (normally called when the thread finishes)."""
        if thread in self.qthreads:
            self.qthreads.remove(thread)

    # threading.Thread management
    def register_thread(self, thread: threading.Thread):
        """
        Register an existing threading.Thread for later shutdown.
        To use if we manually start() the thread.
        """
        if thread not in self.threads:
            self.threads.append(thread)

    def start_thread(self, thread: threading.Thread):
        """
        Register and start a threading.Thread in one step.
        """
        self.register_thread(thread)
        thread.finished.connect(lambda: self.unregister_thread(thread))
        thread.start()

    def unregister_thread(self, thread: threading.Thread) -> None:
        """Remove a threading.Thread from the internal list."""
        if thread in self.threads:
            self.threads.remove(thread)

    # Shutdown
    def shutdown(self):
        """
        Stop all registered threads.
        - QThread: call quit() and wait() until they exit.
        - threading.Thread: join() with a timeout (workers should implement a stop flag if long-running).
        """
        # Stoppe les QThreads
        for t in list(self.qthreads):
            try:
                if sip.isdeleted(t):
                    self.qthreads.remove(t)
                    continue
                if t.isRunning():
                    t.quit()
                    t.wait()
            except RuntimeError:
                pass
        self.qthreads.clear()
        # Stoppe les threading.Threads
        for t in list(self.threads):
            try:
                if t.is_alive():
                    # nécessite un flag stop() côté worker si la boucle est infinie
                    t.join(timeout=5)
            finally:
                # wque ce soit terminé ou qu'on prenne un timed‑out, on abandonne la référence
                if t in self.threads:
                    self.threads.remove(t)
        self.threads.clear()
