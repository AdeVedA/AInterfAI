from pathlib import Path
from typing import List

from PyQt6 import sip
from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.prompt_manager import Callable
from core.rag.config import RAGConfig
from gui.widgets.spinner import create_spinner

from .parser_worker import AnalyzeWorker, TooManyFilesError
from .widgets.context_config_dialog import ContextConfigDialog
from .widgets.small_widgets import add_separator


class FolderRowWidget(QWidget):
    """class to build folder rows in context panel"""

    folderClicked = pyqtSignal()

    def __init__(self, name: str, expanded: bool, toggle_callback):
        super().__init__()
        self.setObjectName("contextRow")
        self.setProperty("isFolder", True)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 8, 0, 2)

        # + / – toggle
        self.btn_toggle = QToolButton()
        self.btn_toggle.setObjectName("btnToggle")
        self.btn_toggle.setText("+" if expanded else "-")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.clicked.connect(toggle_callback)
        h.addWidget(self.btn_toggle)

        # Nom du dossier
        lbl = QLabel(name)
        lbl.setObjectName("lblName")
        h.addWidget(lbl)
        h.addStretch()

    # def mousePressEvent(self, ev):
    #     super().mousePressEvent(ev)
    #     # déclenche le callback
    #     self.folderClicked.emit()  # reçu ds _analyse

    def mouseReleaseEvent(self, event):
        if not self.btn_toggle.geometry().contains(event.pos()):
            if hasattr(self, "path"):  # Sécurité si path est défini après init
                self.folderClicked.emit(self.path)
        super().mouseReleaseEvent(event)


class FileRowWidget(QWidget):
    """class to build file rows in context panel"""

    def __init__(self, name: str):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setObjectName("contextRow")
        self.setProperty("isFolder", False)
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 2, 2, 2)  # indentation
        # checkbox + nom
        self.checkbox = QCheckBox(name)
        h.addWidget(self.checkbox)
        h.addStretch()


class VectorizationWorker(QObject):
    finished = pyqtSignal(int)  # nombre de chunks indexés
    error = pyqtSignal(str)

    def __init__(self, rag_handler, files):
        super().__init__()
        self._rag_handler = rag_handler
        self._files = files

    def run(self):
        try:
            self._rag_handler.purge_collection()
            count = self._rag_handler.index_files(self._files)
            self.finished.emit(count)
        except Exception as e:
            self.error.emit(str(e))
            return


class ContextBuilderPanel(QWidget):
    """
    - Choice of Root folder (+ folder history)
    - Config.ini Edition/Save/Cancel/restore defaults
    - Analysis of the tree structure according to config.ini
    - Folders/Files tree checked/unchecked
    - Live tokens counting
    - Markdown generation
    """

    context_generated = pyqtSignal(str, str)  # markdown, output_path
    new_session_requested = pyqtSignal()  # signal pour demander une nouvelle session
    rag_handler_requested = pyqtSignal(int)

    def __init__(self, parent=None, parser=None, thread_manager=None):
        super().__init__(parent)
        self.thread_manager = thread_manager
        self.current_session_id = None
        self.parser = parser
        self._error_handled = (
            False  # Flag pour gérer l'erreur de dépassement de la limite de fichiers parsés
        )
        self.expanded = set()  # on initialise à l'instanciation, on remplira dans _analyse
        self.folder_items: dict[Path, QTreeWidgetItem] = {}
        # construire l'UI de base (OFF + FULL)
        self._build_ui()
        # RAG pipeline
        self._rag_config = RAGConfig()
        # construire l'UI RAG complémentaire
        self._build_rag_ui()
        # connecter tous les signaux
        self._connect_signals()
        # initialiser l'état selon le mode par défaut (OFF)
        self._on_mode_changed()
        # session_id sera mis à jour via set_session_id()
        self._rag_handler = None

    def _build_ui(self):
        """Builds the UI (for modes OFF/FULL)."""
        self.setObjectName("context_builder_panel")
        self.setMinimumWidth(210)
        self.setMaximumWidth(400)
        main = QVBoxLayout(self)
        main.setSpacing(0)
        main.setContentsMargins(3, 8, 3, 8)

        # Ligne de titre
        lbl_mode = QLabel(" Context ", self)
        lbl_mode.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lbl_mode.setObjectName("context_lbl_mode")
        lbl_mode.setToolTip(
            "Controls how file content is used as context for your LLM requests.\n"
            "- OFF: No file content is included in the request.\n"
            "- Full:  Includes the full content of selected files. Can also export a markdown representation.\n"
            "- RAG:  Uses semantic search to identify and include only the most relevant 'chunks' of text from \n"
            "your files, based on their similarity to your input prompt. This improves performance and reduces cost."
        )
        main.addWidget(lbl_mode)

        add_separator(name="line", layout=main)

        # Ligne switch de mode de contexte (OFF / FULL / RAG)
        h_switch = QHBoxLayout()
        h_switch.setSpacing(0)

        # Création des trois RadioButtons
        self.rb_off = QRadioButton("OFF", self)
        self.rb_off.setObjectName("rb_off")
        self.rb_off.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rb_off.setToolTip("normal chat without context sent other than chat history")

        spacer1 = QWidget(self)
        spacer1.setObjectName("spacer1_wdg")
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.rb_full = QRadioButton("📄 Full", self)
        self.rb_full.setObjectName("rb_full")
        self.rb_full.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rb_full.setToolTip("Include full file content in the prompt")

        spacer2 = QWidget(self)
        spacer2.setObjectName("spacer2_wdg")
        spacer2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.rb_rag = QRadioButton("📚 RAG", self)
        self.rb_rag.setObjectName("rb_rag")
        self.rb_rag.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rb_rag.setToolTip("Include relevant files extracts from the requests in the prompt")
        # Groupement exclusif
        self.mode_group = QButtonGroup(self)
        self.mode_group.setObjectName("btngroup_rag")
        self.mode_group.addButton(self.rb_off, 0)
        self.mode_group.addButton(self.rb_full, 1)
        self.mode_group.addButton(self.rb_rag, 2)

        # Layout
        h_switch.addWidget(self.rb_off)
        h_switch.addWidget(spacer1)
        h_switch.addWidget(self.rb_full)
        h_switch.addWidget(spacer2)
        h_switch.addWidget(self.rb_rag)
        main.addLayout(h_switch)

        # Valeur par défaut
        self.rb_off.setChecked(True)

        # spacer
        spc = QWidget(self)
        main.addWidget(spc)

        add_separator(name="line2", layout=main, thickness=5, top_space=4, bottom_space=7)

        # Root Folder : Chemin(chemins historiques de config) + bouton "ouvrir"
        lbl_root = QLabel(r"Root folder : ⬆/⬇ to navigate", self)
        lbl_root.setAlignment(Qt.AlignmentFlag.AlignLeft)
        lbl_root.setObjectName("context_lbl_root")
        main.addWidget(lbl_root)

        h_path = QHBoxLayout()
        self.path_combo = QComboBox(self)
        self.path_combo.setObjectName("context_path_combo")
        self.path_combo.setEditable(True)
        # for p in self.parser.history:
        #     self.path_combo.addItem(p)
        # if self.path_combo.count() > 0:
        #     self.path_combo.setCurrentIndex(0)
        self.path_combo.setToolTip("")
        self.path_combo.setEnabled(False)
        self.path_combo.clear()
        self.path_combo.lineEdit().clear()
        self.path_combo.currentIndexChanged.connect(
            lambda: self.path_combo.setToolTip(
                f"current context source folder : {Path(self.path_combo.currentText())}"
            )
        )
        # h_path.addWidget(QLabel(""), 1)
        h_path.addWidget(self.path_combo, 5)
        h_path.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        btn_browse = QPushButton("📂", self)
        btn_browse.setObjectName("context_btn_browse")
        btn_browse.setToolTip("Choose a folder")
        h_path.addWidget(btn_browse)
        main.addLayout(h_path)

        add_separator(name="line2", layout=main, thickness=5, top_space=4, bottom_space=7)

        # Boutons Tout cocher / Décocher / éditer le config.ini
        h_sel = QHBoxLayout()
        h_sel.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        btn_all = QPushButton("✓ All", self)
        btn_all.setObjectName("context_btn_all")
        btn_all.setToolTip("Select all files")
        btn_none = QPushButton("☐ None", self)
        btn_none.setObjectName("context_btn_none")
        btn_none.setToolTip("Deselect all files")
        btn_cfg = QPushButton("⚙️ Config", self)
        btn_cfg.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cfg.setObjectName("context_btn_cfg")
        btn_cfg.setToolTip(
            "Configure your presets for file/folder tree parsing filters :\n"
            "file extensions included, folders & files exclusions, gitignore inclusion, history of paths, "
            "number of history paths to keep..."
        )
        h_sel.addWidget(btn_all)
        h_sel.addWidget(btn_none)
        h_sel.addWidget(btn_cfg, alignment=Qt.AlignmentFlag.AlignRight)
        main.addLayout(h_sel)

        # Arbre des fichiers
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("context_file_tree")
        self.tree.setHeaderLabels([" Folders / Files", " Tokens"])
        self.tree.setColumnWidth(1, 44)
        # laissez Qt gérer l'indentation des enfants
        self.tree.setIndentation(2)
        header = self.tree.header()
        # Autoriser le redimensionnement minimal
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        # SizePolicy pour que le widget puisse devenir étroit
        self.tree.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        main.addWidget(self.tree, 1)

        spacer1 = QWidget(self)
        spacer1.setObjectName("spacer1_wdg")
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        main.addWidget(spacer1)

        # Compte-tokens live
        self.lbl_tokens = QLabel("Context total tokens: 0", self)
        self.lbl_tokens.setObjectName("context_lbl_tokens")
        main.addWidget(self.lbl_tokens, alignment=Qt.AlignmentFlag.AlignRight)

        # Bouton Générer
        btn_gen = QPushButton("Export context in Markdown", self)
        btn_gen.setObjectName("context_btn_generate")
        btn_gen.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_gen.setToolTip("Generate a Markdown file for external use...")
        main.addWidget(btn_gen)

        # Stocker pour connexions
        self._btn_browse = btn_browse
        self._btn_cfg = btn_cfg
        self._btn_all = btn_all
        self._btn_none = btn_none
        self._btn_gen = btn_gen

    def _build_rag_ui(self):
        """Builds specific controls for RAG mode, invisible by default."""
        # Bouton vectorisation
        self._btn_rag_vectorize = QPushButton("Context vectorization", self)
        self._btn_rag_vectorize.setObjectName("context_btn_vectorize")
        self._btn_rag_vectorize.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_rag_vectorize.setToolTip("Start the vectorization of your file selection")
        self._btn_rag_vectorize.hide()

        # Spinner simplifié (icône de recharge)
        # self._lbl_spinner = QLabel("🔄", self)
        self._lbl_spinner = create_spinner(
            text="Vectorization Processing...",
            object_name="rag_spinner",
            style="",
        )
        self._lbl_spinner.hide()
        self._analyse_spinner = create_spinner(
            text="Scanning files ...", object_name="scan_spinner", style=""
        )
        self._analyse_spinner.hide()

        # Message de statut
        self._lbl_rag_status = QLabel("", self)
        self._lbl_rag_status.setObjectName("vectorized")
        self._lbl_rag_status.hide()

        # Paramètres RAG : K et chunk_size + rafraîchir
        self._sb_k = QSpinBox(self)
        self._sb_k.setObjectName("sb_k")
        self._sb_k.setRange(1, 100)
        self._sb_k.setValue(int(self._rag_config.k))
        self._sb_k.setToolTip("Number of chunks to recover")
        self._sb_k.hide()
        self._sb_k.valueChanged.connect(self._on_k_changed)
        self._sb_chunk = QSpinBox(self)
        self._sb_chunk.setObjectName("sb_chunk")
        self._sb_chunk.setRange(100, 5000)
        self._sb_chunk.setValue(int(self._rag_config.chunk_size))
        self._sb_chunk.setToolTip("Chunks size")
        self._sb_chunk.hide()
        self._sb_chunk.valueChanged.connect(self._on_chunk_changed)

        self._btn_refresh_index = QPushButton("Refresh the index", self)
        self._btn_refresh_index.setObjectName("context_btn_refresh")
        self._btn_refresh_index.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh_index.setToolTip("Refresh the files indexes")

        # Layout RAG
        h_rag_btns = QHBoxLayout()
        h_rag_btns.addWidget(self._btn_rag_vectorize)
        self.layout().addLayout(h_rag_btns)
        h_rag_stat = QHBoxLayout()
        h_rag_stat.addWidget(self._lbl_spinner, alignment=Qt.AlignmentFlag.AlignHCenter)
        h_rag_stat.addWidget(self._analyse_spinner, alignment=Qt.AlignmentFlag.AlignHCenter)
        h_rag_stat.addWidget(self._lbl_rag_status, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.layout().addLayout(h_rag_stat)

        h_rag_params = QHBoxLayout()
        self._lbl_k_label = QLabel("K extracts ", self)
        self._lbl_k_label.setObjectName("lbl_k_label")
        h_rag_params.addWidget(self._lbl_k_label)
        h_rag_params.addWidget(self._sb_k)

        spacer1 = QWidget(self)
        spacer1.setObjectName("spacer1_wdg")
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h_rag_params.addWidget(spacer1)

        self._lbl_chunk_label = QLabel("Chunk size ", self)
        self._lbl_chunk_label.setObjectName("lbl_chunk_label")
        h_rag_params.addWidget(self._lbl_chunk_label, alignment=Qt.AlignmentFlag.AlignRight)
        h_rag_params.addWidget(self._sb_chunk, alignment=Qt.AlignmentFlag.AlignRight)

        self.layout().addLayout(h_rag_params)

        h_rag_refresh = QHBoxLayout()
        h_rag_refresh.addWidget(self._btn_refresh_index)
        self.layout().addLayout(h_rag_refresh)

        # Cacher tout
        for w in (
            self._btn_rag_vectorize,
            self._lbl_spinner,
            self._lbl_rag_status,
            self._sb_k,
            self._sb_chunk,
            self._btn_refresh_index,
        ):
            w.hide()

    def _connect_signals(self):
        self._btn_browse.clicked.connect(self._choose_folder)
        self._btn_cfg.clicked.connect(self._edit_config)
        self._btn_all.clicked.connect(self._select_all)
        self._btn_none.clicked.connect(self._select_none)
        self._btn_gen.clicked.connect(self._on_generate)
        self.path_combo.activated.connect(lambda idx: self._analyze())
        self.path_combo.lineEdit().returnPressed.connect(self._analyze)
        # mode switch OFF/Full/RAG
        for btn in self.mode_group.buttons():
            btn.toggled.connect(self._on_mode_changed)

        # RAG
        self._btn_rag_vectorize.clicked.connect(self._on_rag_vectorize)
        self._btn_refresh_index.clicked.connect(self._on_refresh_index)

    def attach_processor(self, processor):
        """give to context panel an access to UserMessageProcessor"""
        self._processor = processor

    def _on_k_changed(self, value: int):
        self._rag_config.k = int(value)

    def _on_chunk_changed(self, value: int):
        self._rag_config.chunk_size = int(value)

    def _refresh_path_combo(self) -> None:
        """Empty the Qcombox and fills it with current context config's history paths."""
        self.path_combo.blockSignals(True)  # éviter les déclenchements parasites
        self.path_combo.clear()
        for p in self.parser.history:  # parser.history provient de la propriété
            self.path_combo.addItem(p)
        if self.path_combo.count() > 0:
            self.path_combo.setCurrentIndex(0)  # sélectionner le premier
            self.path_combo.setToolTip(
                f"current context source folder : {Path(self.path_combo.currentText())}"
            )
        else:
            self.path_combo.setToolTip("No context source folder available")
        self.path_combo.blockSignals(False)

    def _on_mode_changed(self):
        """when boutons [OFF, Full, RAG] are clicked,
        activate/unable/displays/hides/refresh the panel's needed components."""
        mode = self.mode_group.checkedId()  # 0=OFF,1=FULL,2=RAG
        active = mode in (1, 2)
        # activer/désactiver tout
        self.path_combo.setEnabled(active)
        if not active:
            self.path_combo.clear()
            self.tree.clear()
        else:
            self._refresh_path_combo()
        self._btn_browse.setEnabled(active)
        self.tree.setEnabled(active)
        self._btn_all.setEnabled(active)
        self._btn_none.setEnabled(active)
        self._btn_cfg.setEnabled(active)
        # FULL : bouton _btn_gen
        self._btn_gen.setVisible(mode == 1)
        self._btn_gen.setEnabled(mode == 1)
        # RAG : vectorize + params
        for w in (
            self._btn_rag_vectorize,
            self._lbl_k_label,
            self._sb_k,
            self._lbl_chunk_label,
            self._sb_chunk,
            self._btn_refresh_index,
        ):
            w.setVisible(mode == 2)
            w.setEnabled(mode == 2)
        # spinner & statut cachés au changement
        self._lbl_spinner.hide()
        self._lbl_rag_status.hide()

        if active:
            self._analyze()

        # Si on vient de passer en RAG et qu'on a déjà un session_id, crée/rafraîchis le handler
        if (
            mode == 2
            and getattr(self, "current_session_id", None)
            and getattr(self, "_processor", None)
        ):
            self.rag_handler_requested.emit(self.current_session_id)
            try:
                self._rag_handler = self._processor.ensure_and_get_rag_handler(
                    self.current_session_id
                )
            except Exception as e:
                print(f"ContextBuilder - unable to ensure RAGHandler: {e}")
            self._rag_handler = None
        elif mode != 2:
            self._rag_handler = None

    def _on_rag_vectorize(self):
        """Starts RAG vectorization."""
        # Si pas de session encore sélectionnée, on la crée puis on relance _on_rag_vectorize 100ms plus tard
        if not getattr(self, "current_session_id", None):
            self.new_session_requested.emit()
            QTimer.singleShot(100, self._on_rag_vectorize)
            return

        # if self._rag_handler is None or self._rag_handler.session_id != self.current_session_id:
        #     self._rag_handler = RAGHandler(self._rag_config, self.current_session_id)
        if (
            self._rag_handler is None or self._rag_handler.session_id != self.current_session_id
        ) and getattr(self, "_processor", None):
            try:
                self._rag_handler = self._processor.ensure_and_get_rag_handler(
                    self.current_session_id
                )
            except Exception as e:
                QMessageBox.warning(
                    self, "Error", f"The RAG manager could not be initialized:\n{e}"
                )
                return

        if self._rag_handler is None:
            QMessageBox.warning(
                self,
                "Error",
                "The Rag manager is not initialized. Please create/select a session first.",
            )
            return
        files = self.selected_files()
        # print(f"debug : fichiers sélectionnés pour RAG : {files}")
        if not files:
            QMessageBox.information(self, "Info", "No file selected for RAG.")
            return

        self._btn_rag_vectorize.setEnabled(False)
        self._lbl_spinner.show()
        self._lbl_rag_status.hide()

        # -- Thread
        self._thread = QThread(self)
        self._worker = VectorizationWorker(self._rag_handler, files)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_vectorization_done)
        self._worker.error.connect(self._on_vectorization_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_vectorization_done(self, count: int):
        """Displays the result of the vectorization."""
        self._lbl_spinner.hide()
        self._lbl_rag_status.setText(f"Vectorization done :\n{count} chunks indexed")
        self._lbl_rag_status.show()
        self._btn_rag_vectorize.setEnabled(True)

    def _on_vectorization_error(self, msg: str):
        self._lbl_spinner.hide()
        self._btn_rag_vectorize.setEnabled(True)
        self._lbl_rag_status.setText(f"Vectorization failed :\n{msg}")
        self._lbl_rag_status.show()

    def _on_refresh_index(self):
        print(
            "Index refreshed with K =", self._sb_k.value(), "chunk_size =", self._sb_chunk.value()
        )

    def get_context_mode(self) -> int:
        """Returns the current context mode : 0=OFF, 1=FULL, 2=RAG"""
        return self.mode_group.checkedId()

    def set_session_id(self, session_id: int):
        """Registers the session_id as instance's attribute"""
        self.current_session_id = session_id

    def build_rag_prompt(self, query: str) -> str:
        if self._rag_handler is None:
            raise RuntimeError("No Raghandler is initialized.")
        return self._rag_handler.build_rag_prompt(query, allowed_paths=self.selected_files())

    def _choose_folder(self):
        """QFileDilaog box to choose the source folder for context files selection"""
        d = QFileDialog.getExistingDirectory(self, "Choose the documents' parent Folder")
        if d:
            self.path_combo.setCurrentText(d)
            self.parser.add_to_history(d)
            # remplir combo et recharger histoire
            self.path_combo.clear()
            for p in self.parser.history:
                self.path_combo.addItem(p)
            self._analyze()

    def _analyze(self, forced_limit: bool = False):
        """Analyse the directory in a QTHREAD via ThreadManager."""
        if not self.path_combo.currentText():
            return
        base = Path(self.path_combo.currentText())

        if not base.is_dir():
            QMessageBox.warning(self, "Error", "Invalid folder")
            return

        old_thread = getattr(self, "_scan_thread", None)
        #  Si un scan était déjà en cours : l'interrompre proprement
        if (
            isinstance(old_thread, QThread)
            and not sip.isdeleted(old_thread)
            and old_thread.isRunning()
        ):
            old_thread.quit()
            old_thread.wait()  # attendre la fin du thread précédent

        self._analyse_spinner.show()
        self._error_handled = False  # on reset le flag
        # Affichage d'un spinner et désactivation temporaire des contrôles
        self._btn_all.setEnabled(False)
        self._btn_none.setEnabled(False)
        self._btn_gen.setEnabled(False)

        # Création du worker / thread
        self._scan_thread = QThread(self)  # thread local au panel
        self._scan_worker = AnalyzeWorker(self.parser, base, forced_limit=forced_limit)
        self._scan_worker.moveToThread(self._scan_thread)

        # connexions
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_analyze_finished)
        self._scan_worker.error.connect(self._on_analyze_error)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.error.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_worker.error.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)

        # Démarrage via ThreadManager
        self.thread_manager.start_qthread(self._scan_thread)

    def _on_analyze_finished(self, files: List[Path]) -> None:
        """Built the Tree once the list has been obtained."""
        self._analyse_spinner.hide()
        self._btn_all.setEnabled(True)
        self._btn_none.setEnabled(True)
        self._btn_gen.setEnabled(self.get_context_mode() == 1)

        base = Path(self.path_combo.currentText())
        # 1) Récupérer la liste des fichiers cochés AVANT de tout vider :
        prev_checked = set(self.selected_files())

        # files = self.parser.list_files(base)

        self.tree.clear()
        self.folder_items.clear()
        # Initialement, TOUS les dossiers sont ouverts
        self.expanded = set(p.parent for p in files) | {base}

        # Grouper par parent
        from collections import defaultdict

        by_parent = defaultdict(list)
        for f in files:
            by_parent[f.parent].append(f)

        # Ordre des parents : base d'abord, puis les autres triés
        parents = list(by_parent.keys())
        parents.sort(key=lambda p: (p != base, str(p.relative_to(base))))

        for parent in parents:
            # 1) Créer l'item dossier
            it = QTreeWidgetItem(self.tree, ["", ""])
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            it.setData(0, Qt.ItemDataRole.UserRole, parent)
            self.folder_items[parent] = it

            # une ou deux closures pour verrouiller "parent"
            def make_toggle_children(p):
                return lambda: self._on_folder_children_toggle(p)

            # def make_toggle_openclose(p):
            #    return lambda: self._on_folder_toggle_clicked(p)

            w = FolderRowWidget(
                name=(
                    f"📂--{str(base).split("\\")[-1].upper()}--📂"
                    if parent == base
                    else str(parent.relative_to(base))
                ),
                expanded=(parent in self.expanded),
                toggle_callback=make_toggle_children(parent),
            )
            # clic n'importe où sur la ligne = open/close
            # ➜ connecte directement le signal folderClicked (qui capte tout sauf +/–)
            w.folderClicked.connect(lambda p=parent: self._on_folder_toggle_clicked(p))
            self.tree.setItemWidget(it, 0, w)

            # 3) Si ouvert, ajouter ses fichiers
            if parent in self.expanded:
                for f in by_parent[parent]:
                    fi = QTreeWidgetItem(it, ["", ""])
                    # pas de flag checkable sur l'item : on utilise uniquement notre checkbox
                    fi.setFlags(fi.flags() & Qt.ItemFlag.ItemIsUserCheckable)
                    fi.setData(0, Qt.ItemDataRole.UserRole, f)

                    # Colonne Tokens
                    lbl_t = QLabel(str(self.parser.count_tokens(f)))
                    lbl_t.setObjectName("lblTokens")
                    lbl_t.setAlignment(Qt.AlignmentFlag.AlignRight)
                    # rendre cliquable pour toggle du dossier parent
                    orig_mouse = lbl_t.mouseReleaseEvent

                    def token_click(ev, p=parent):  # injection de gestion du clic tokens
                        if ev.button() == Qt.MouseButton.LeftButton:
                            self._on_folder_toggle_clicked(p)
                        return orig_mouse(ev)

                    lbl_t.mouseReleaseEvent = token_click
                    self.tree.setItemWidget(fi, 1, lbl_t)

                    # Colonne Nom + checkbox
                    wf = FileRowWidget(name=f.name)
                    # **restauration** de l'état coché
                    if f in prev_checked:
                        wf.checkbox.setChecked(True)
                    wf.checkbox.stateChanged.connect(
                        lambda st, item=fi: self._on_context_check_changed(item, st)
                    )
                    self.tree.setItemWidget(fi, 0, wf)

        self.tree.expandAll()
        self._recompute_tokens()
        self._scan_thread = None
        self._scan_worker = None

    def _clean_thread(self):
        self._scan_thread = None
        self._scan_worker = None

    def _on_analyze_error(self, msg: str) -> None:
        """Displays the error and possibly proposes to continue with a subset."""
        self._analyse_spinner.hide()
        self._btn_all.setEnabled(True)
        self._btn_none.setEnabled(True)
        self._btn_gen.setEnabled(self.get_context_mode() == 1)

        if self._error_handled:
            return
        self._error_handled = True
        if (
            isinstance(msg, TooManyFilesError) or "More than" in msg
        ):  # provenance de TooManyFilesError
            reply = QMessageBox.question(
                self,
                "Too many files",
                f"{msg}\n\nDo you want to continue with the first {self.parser.max_files:,} files ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                # on relance l'analyse ; le worker renverra la liste tronquée
                self._clean_thread()
                # self._scan_thread = None
                # self._scan_worker = None
                self._analyze(forced_limit=True)
                return
            self._clean_thread()
            # self._scan_thread = None
            # self._scan_worker = None
            return

        QMessageBox.critical(self, "Scanning error", msg)
        self._clean_thread()
        # self._scan_thread = None
        # self._scan_worker = None

    def _on_folder_toggle_clicked(self, folder_path: Path):
        """Click on the +/- of folder : toggles and reloads. Called from folderClicked signal"""
        if folder_path in self.expanded:
            self.expanded.remove(folder_path)
        else:
            self.expanded.add(folder_path)
        self._analyze()

    def _on_folder_children_toggle(self, folder_path: Path):
        """
        Button click +/- -> Check/Uncheck all children's files.
        """
        root_item = self.folder_items[folder_path]
        # déterminer nouvel état = si un au moins non-coché -> on coche tous, sinon on décoche tous
        to_check = any(
            isinstance(self.tree.itemWidget(child, 0), FileRowWidget)
            and not self.tree.itemWidget(child, 0).checkbox.isChecked()
            for child in (root_item.child(i) for i in range(root_item.childCount()))
        )
        # appliquer
        for i in range(root_item.childCount()):
            child = root_item.child(i)
            w = self.tree.itemWidget(child, 0)
            if isinstance(w, FileRowWidget):
                w.checkbox.setChecked(to_check)

    def _on_context_check_changed(self, item: QTreeWidgetItem, state: int):
        """
        StateChanged of QCheckBox in FileRowWidget.
        We recalculate and update the property 'checked' for QSS.
        """
        # 1) recalculer le total
        self._recompute_tokens()

        # 2) taguer le widget pour le QSS
        w = self.tree.itemWidget(item, 0)
        if isinstance(w, FileRowWidget):
            is_checked = state == Qt.CheckState.Checked
            w.setProperty("checked", is_checked)
            w.style().unpolish(w)
            w.style().polish(w)

    def _traverse_tree(self, fn: Callable[[QTreeWidgetItem], None]):
        """
        Travels recursively all the QTreeWidgetItem (folders + files)
        and calls fn(item) on everyone.
        """

        def recurse(item: QTreeWidgetItem):
            fn(item)
            for i in range(item.childCount()):
                recurse(item.child(i))

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            recurse(root.child(i))

    def _recompute_tokens(self):
        """Sum the tokens displayed in the column 1 for each FileRowWidget checked."""
        total = 0

        def collect(itm: QTreeWidgetItem):
            w = self.tree.itemWidget(itm, 0)
            if isinstance(w, FileRowWidget) and w.checkbox.isChecked():
                lbl = self.tree.itemWidget(itm, 1)
                if isinstance(lbl, QLabel) and lbl.text().isdigit():
                    nonlocal total
                    total += int(lbl.text())

        self._traverse_tree(collect)
        self.lbl_tokens.setText(f"Total tokens: {total}")

    def _select_all(self):
        """Check all FileRowWidget.checkbox"""
        self._traverse_tree(
            lambda itm: (
                isinstance(self.tree.itemWidget(itm, 0), FileRowWidget)
                and self.tree.itemWidget(itm, 0).checkbox.setChecked(True)
            )
        )

    def _select_none(self):
        """Uncheck all FileRowWidget.checkbox"""
        self._traverse_tree(
            lambda itm: (
                isinstance(self.tree.itemWidget(itm, 0), FileRowWidget)
                and self.tree.itemWidget(itm, 0).checkbox.setChecked(False)
            )
        )

    def selected_files(self) -> list[Path]:
        """Return the list of checked Paths"""
        files: list[Path] = []

        def collect(item: QTreeWidgetItem):
            # on cherche notre FileRowWidget en colonne 0
            w0 = self.tree.itemWidget(item, 0)
            if isinstance(w0, FileRowWidget) and w0.checkbox.isChecked():
                files.append(item.data(0, Qt.ItemDataRole.UserRole))

        self._traverse_tree(collect)
        return files

    def _on_generate(self):
        """Generates the Markdown, offers a file name and emits Context_generated."""
        files = self.selected_files()
        if not files:
            QMessageBox.information(self, "Info", "No selected file.")
            return

        # Génération via ContextParser
        md = self.parser.generate_markdown(files, mode="Code")

        # Boîte de dialogue pour sauver
        out_path, _ = QFileDialog.getSaveFileName(self, "Save Markdown", filter="Markdown (*.md)")
        if not out_path:
            return

        # Sauvegarde du Markdown
        self.parser.save_markdown(md, Path(out_path))

        QMessageBox.information(self, "Finished", f"Context generated : {out_path}")
        # Émission du signal pour la suite (MainWindow)
        self.context_generated.emit(md, out_path)

    def set_config_name(self, name: str):
        """Called from MainWindow.load_gui_config()."""
        self.parser.config_name = name
        # mettre à jour visuellement le combo
        self._on_mode_changed()
        # relancer l'analyse si on est en mode FULL ou RAG
        if self.mode_group.checkedId() != 0:
            QTimer.singleShot(0, self._analyze)

    def _edit_config(self):
        """Instanciate a `ContextConfigDialog` Box with presets tabs to select and edit config presets.
        If the QDialog box is accepted (ok), the active preset tab is selected to filter the context parsing _analyse
        """
        dlg = ContextConfigDialog(parent=self, parser=self.parser)
        # s'assure que l'onglet actif est sélectionné
        dlg.select_config(self.parser.config_name)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # parser a déjà été mis à jour, on analyse le rep
            self._analyze()
            pass
