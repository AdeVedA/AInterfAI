import faulthandler
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv
from PyQt6.QtCore import QTimer, QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication


def _qt_message_handler(msg_type, context, msg):
    """Intercept and masks QPainter messages when fullscreen resize"""
    text = msg.data().decode() if hasattr(msg, "data") else str(msg)
    # On ignore les warnings de QPainter débutant sans engine
    if text.startswith("QPainter::"):
        return
    # Réémettre tous les autres messages
    if msg_type == QtMsgType.QtDebugMsg:
        sys.stdout.write(text + "\n")
    else:
        sys.stderr.write(text + "\n")
    sys.stdout.flush()
    sys.stderr.flush()


def handle_exception(exc_type, exc_value, exc_tb):
    """Handle uncaught exceptions and log them."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    print("Uncaught exception:")
    traceback.print_exception(exc_type, exc_value, exc_tb)
    sys.stderr.flush()


def main():
    faulthandler.enable(all_threads=True, file=sys.stderr)

    load_dotenv()
    BASE_DIR = Path(__file__).resolve().parent
    # variables d'environnement
    QDRANT_EXE = os.getenv("QDRANT_ENGINE_PATH", "")
    if not QDRANT_EXE:
        from utils.env_tools import ensure_qdrant_path

        dotenv_file = BASE_DIR / ".env"
        QDRANT_EXE = ensure_qdrant_path(dotenv_file)
    QDRANT_HOST = "127.0.0.1"
    # QDRANT_HTTP_PORT = int(os.getenv("QDRANT_HTTP_PORT", "6333"))
    QDRANT_GRPC_PORT = int(os.getenv("QDRANT_GRPC_PORT", "6334"))
    QDRANT_CONFIG = BASE_DIR / "utils" / "config.yaml"

    # Installer le filtre/les handlers avant que Qt n'initialise quoi que ce soit
    qInstallMessageHandler(_qt_message_handler)
    sys.excepthook = handle_exception

    # Créer QApplication de suite pour que Qt commence à initialiser
    app = QApplication(sys.argv)
    # Choisir la police globale
    app.setFont(QFont("Calibri", 13))
    app.setWindowIcon(QIcon("assets\\icon.ico"))

    # Initialiser la BDD
    from core.database import init_db

    init_db()

    # Charger Qdrant (BDD vectorielle)
    from utils.qdrant_launcher import QdrantLauncher

    qlauncher = QdrantLauncher(QDRANT_EXE, QDRANT_HOST, QDRANT_GRPC_PORT, str(QDRANT_CONFIG))
    qlauncher.launch()

    # à la fermeture, arrêter Qdrant proprement
    app.aboutToQuit.connect(qlauncher.stop)

    # Instancier les managers métiers
    from core.config_manager import ConfigManager
    from core.llm_manager import LLMManager
    from core.session_manager import SessionManager
    from core.theme.theme_manager import ThemeManager

    config_manager = ConfigManager()
    session_manager = SessionManager()
    llm_manager = LLMManager(session_manager=session_manager)
    theme_manager = ThemeManager(app)

    # Importer après QApplication et managers pour alléger l'import initial
    from gui.gui import MainWindow

    window = MainWindow(
        config_manager,
        theme_manager,
        session_manager,
        llm_manager,
    )
    # Montrer la fenêtre immédiatement
    window.show()

    # Différer le travail « lourd » (chargement des sessions, des prompt config...)
    # pour qu'il démarre après que Qt ait affiché la fenêtre.
    QTimer.singleShot(0, lambda: (window.refresh_sessions(), window.on_load_role_llm_config()))

    # Entrer dans la boucle Qt
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
