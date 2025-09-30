import re
import sys

from PyQt6 import QtCore
from PyQt6.QtCore import (
    Q_ARG,
    QEvent,
    QMetaObject,
    QPoint,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QClipboard, QFont, QKeySequence, QShortcut, QTextOption, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.search_dialog import SearchDialog
from gui.widgets.spinner import create_spinner

from .renderer_worker import RendererWorker


class InputTextEdit(QTextEdit):
    """
    Multiline text input that emits a send signal on Enter (without Shift).
    Auto-resizes up to half of parent height, then scrolls.
    """

    send = pyqtSignal(str)

    def __init__(self, parent=None, ctx_parser=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        # Permet au widget de croître et de rétrécir
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(40)
        self.setPlaceholderText("Write your prompt here\nPress 'CTRL+Enter' to submit")
        self.setObjectName("input_textedit")
        self.ctx_parser = ctx_parser

        self.input_token_count = QLabel("0\ntokens", self)
        self.input_token_count.setObjectName("chatinput_token_count")
        self.input_token_count.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.input_token_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        # self.input_token_count.setFixedHeight(16)

        self.textChanged.connect(self._on_text_changed)
        self.textChanged.connect(self.adjust_height)

        self._on_text_changed()  # initial update

    def keyPressEvent(self, event):
        # Shift+Enter: insert newline
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() == Qt.KeyboardModifier.ShiftModifier
        ):
            super().keyPressEvent(event)
        # Control+Enter: send
        elif (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            text = self.toPlainText().strip()
            if text:
                self.send.emit(text)
                self.clear()
        else:
            super().keyPressEvent(event)

    def _on_text_changed(self):
        text = self.toPlainText() or ""
        n_tokens = self.ctx_parser.count_tokens_from_text(text)
        self.input_token_count.setText(f"{n_tokens}\ntokens")
        self._reposition_token_label()

    def _reposition_token_label(self):
        margin = 6
        label_w = self.input_token_count.sizeHint().width()
        label_h = self.input_token_count.sizeHint().height()
        edit_w = self.viewport().width()
        edit_h = self.viewport().height()
        x = edit_w - label_w - margin
        y = edit_h - label_h - margin
        self.input_token_count.move(x, y)
        self.input_token_count.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._reposition_token_label)

    def adjust_height(self):
        clamp_height = self.parent().height() // 8
        max_h = self.parent().height() - clamp_height

        self.setMaximumHeight(max_h)
        self.updateGeometry()


class DualLogger:
    """class to catch console messages to print in the chatpanel's console_overlay"""

    def __init__(self, text_edit: QPlainTextEdit, original_stdout):
        self.text_edit = text_edit
        self.original_stdout = original_stdout

    def write(self, msg):
        if msg.strip():  # éviter les lignes vides
            self.text_edit.appendPlainText(msg)
        self.original_stdout.write(msg)

    def flush(self):
        self.original_stdout.flush()
        pass  # nécessaire pour respecter l'interface de sys.stdout


# ChatPanel : manages display, style, and LLM chunked streaming
class ChatPanel(QWidget):
    """
    Main chat panel : History, user entry, LLM streaming.
    Signals :
        user_message(str) - Emitted when the user sends a message.
        font_size_change(int) - Emitted when the user modifies Ctrl+wheel (Police zoom)
    """

    user_message = pyqtSignal(str)
    font_size_changed = pyqtSignal(int)
    stop_requested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        current_session_id: int | None = None,
        theme_manager=None,
        toolbar=None,
        ctx_parser=None,
        session_manager=None,
        thread_manager=None,
    ):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.toolbar = toolbar
        self.session_manager = session_manager
        self.thread_manager = thread_manager
        self.ctx_parser = ctx_parser
        self.search_dialog = None

        self.setObjectName("chat_panel")
        self._min_font_size = 8
        self._max_font_size = 32
        self.setMinimumWidth(380)
        self.setMinimumHeight(720)
        self.setContentsMargins(0, 2, 0, 1)
        self.current_session_id = current_session_id
        # Initialisation du RendererWorker dans un QThread
        self._renderer_thread = QThread(self)
        self._renderer_worker = RendererWorker(theme_manager=self.theme_manager)
        self._renderer_worker.moveToThread(self._renderer_thread)
        self.thread_manager.register_qthread(self._renderer_thread)
        self._renderer_thread.start()
        # Connecter les signaux du worker
        self._renderer_worker.rendered.connect(self._onRenderedHtml)
        self._renderer_worker.error.connect(self._onRenderError)
        # Connecter le signal pour appliquer le CSS
        self._renderer_worker.css_ready.connect(self._apply_global_css)

        # Quand le thème change, demander le CSS au worker
        self.toolbar.theme_changed.connect(self._renderer_worker.send_current_css)
        # Appliquer CSS initial
        self._renderer_worker.send_current_css()

        # mapping index -> widget cible (pour mettre à jour le HTML renvoyé)
        # index sera l'ID de message ou un entier séquentiel
        self._bubbles_by_index = {}

        self._init_ui()

        self._init_state()

        # overlay buttons
        vp = self.history_scroll.viewport()
        self._btn_delete = QPushButton("🗑️")
        self._btn_delete.setToolTip("delete the message")
        self._btn_edit = QPushButton("✏️")
        self._btn_edit.setToolTip("edit the raw message")
        self._btn_copy = QPushButton("📋")
        self._btn_copy.setToolTip("copy raw message into clipboard")
        for btn in (self._btn_delete, self._btn_edit, self._btn_copy):
            btn.setFixedSize(32, 32)
            btn.setParent(vp)
            btn.hide()
        self._btn_delete.setObjectName("btn_delete")
        self._btn_edit.setObjectName("btn_edit")
        self._btn_copy.setObjectName("btn_copy")

        # Stop button en overlay
        self._btn_stop = QPushButton("⏹ Stop", self)
        self._btn_stop.setObjectName("btn_stop_stream")
        self._btn_stop.hide()
        self._btn_stop.clicked.connect(self._handle_stop_clicked)

        # timer d'update de la bulle de streaming pour éviter les "sauts d'affichage"
        self._bubble_update_timer = QTimer(self)
        self._bubble_update_timer.setInterval(150)  # 150 ms = 6-7 renders/s
        self._bubble_update_timer.setSingleShot(True)
        self._bubble_update_timer.timeout.connect(self._apply_deferred_bubble_adjustments)

        self.installEventFilter(self)
        vp.installEventFilter(self)
        self.input.installEventFilter(self)
        self.input.viewport().installEventFilter(self)
        self.history_scroll.verticalScrollBar().valueChanged.connect(self._reposition_overlays)
        self._active_bubble = None

    def _init_ui(self):
        """Initializes the interface : layout, history, splitter, input.
        self (QWidget)
        └── layout (QVBoxLayout)
            └── vsplit (QSplitter Vertical)
                ├── history_scroll (QScrollArea)
                │   └── history_area (QWidget)
                │       └── history_layout (QVBoxLayout)
                │           └── [message bubbles (widgets)]
                └── input (InputTextEdit)
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Zone historique scrollable, conteneur (invisible) qui contient toutes les bulles du chat (les messages).
        self.history_area = QWidget()
        # Layout d'empilement vertical des bulles de chat à l'intérieur de history_area dont il hérite.
        self.history_layout = QVBoxLayout(self.history_area)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_layout.setContentsMargins(5, 5, 5, 5)  # marges globales
        self.history_layout.setSpacing(8)  # espacement entre bulles
        # Zone scrollable contenant history_area, permet le défilement des messages.
        self.history_scroll = QScrollArea(self)
        self.history_scroll.setObjectName("chat_history_scroll")
        self.history_scroll.setContentsMargins(0, 0, 0, 0)
        self.history_scroll.setViewportMargins(0, 0, 0, 0)
        self.history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setWidget(self.history_area)
        # Sans scroll horizontal
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.history_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        # Split input / history
        vsplit = QSplitter(Qt.Orientation.Vertical, self)
        vsplit.setObjectName("in_chat_splitter")
        vsplit.setContentsMargins(0, 0, 0, 0)
        # vsplit.setHandleWidth(10)
        vsplit.addWidget(self.history_scroll)

        self._init_console_overlay()

        # User Input bubble
        self.input = InputTextEdit(self, ctx_parser=self.ctx_parser)
        self.input.setObjectName("chat_input")
        self.input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Police par défaut
        self._default_font_size = 16
        default_font = QFont(self.history_area.font().family(), self._default_font_size)
        self.history_area.setFont(default_font)
        self.input.setFont(default_font)

        vsplit.addWidget(self.input)

        # installer le filtre d'événements sur le scroll et l'input
        self.history_scroll.installEventFilter(self)
        self.history_area.installEventFilter(self)
        self.input.send.connect(self._emit_message)

        # Split history/input (index, stretch)
        vsplit.setStretchFactor(0, 5)  # history
        vsplit.setStretchFactor(1, 1)  # input
        total_height = self.height()
        vsplit.setSizes([int(total_height * 0.8), int(total_height * 0.2)])

        layout.addWidget(vsplit)

        # insert sur stdout/stderr pour bus de redirection vers console
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = DualLogger(self.console_output, self._original_stdout)
        sys.stderr = DualLogger(self.console_output, self._original_stderr)

    def _init_state(self):
        """Initializes streaming and parsing states."""
        self._last_bubble_width = None
        self.llm_streaming_started = False  # état du streaming
        self.auto_scroll_enabled = True  # auto-scroll vers le bas par defaut
        self._block_wheel_scroll = (
            False  # pour bloquer les scoll molettes dans ctrl+molette (zoom)
        )
        self._current_render_message_id = None
        self.llm_bubble_widget = None
        self.llm_waiting_widget = None
        self._stream_buffer = ""  # buffer used for throttled rendering

        # Timer unique pour le batch de rendu
        self._batch_render_timer = QTimer(self)
        self._batch_render_timer.setInterval(650)  # 150 ms = 6-7 renders/s
        self._batch_render_timer.setSingleShot(False)
        self._batch_render_timer.timeout.connect(self._flush_batch_render)

    def _init_console_overlay(self):
        """Adds a floating debug panel at the top with chevron toggle, for the console output and token counter."""
        # Widget flottant par dessus
        self.console_overlay = QWidget(self)
        self.console_overlay.setObjectName("console_overlay")

        self.console_overlay.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.console_overlay.setMinimumSize(0, 0)
        self.console_overlay.setFixedHeight(22)
        self.console_overlay.setGeometry(self.rect())
        self.console_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.console_overlay.raise_()  # Important pour être par dessus tout

        # Layout horizontal serré, sans marges larges
        layout = QHBoxLayout(self.console_overlay)
        layout.setContentsMargins(2, 0, 2, 2)
        layout.setSpacing(10)

        self._btn_toggle_console = QPushButton("▼\n ", self.console_overlay)
        self._btn_toggle_console.setObjectName("console_btn_toggle_console")
        self._btn_toggle_console.setFixedSize(16, 12)
        self._btn_toggle_console.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_toggle_console.setCheckable(True)
        self._btn_toggle_console.setToolTip("Show/hide the console")

        self._btn_toggle_console.toggled.connect(self._toggle_console_output)

        self.btn_clear = QPushButton("🧹 clear console ", self.console_overlay)
        self.btn_clear.setObjectName("console_btn_clear")
        # self.btn_clear.setFixedSize(100, 14)
        self.btn_clear.setVisible(False)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setToolTip("Erase the console content")

        self.btn_clear.clicked.connect(lambda: self.console_output.clear())

        self.history_token_count_label = QLabel("History total tokens : ", self.console_overlay)
        self.history_token_count_label.setVisible(False)
        self.history_token_count_label.setObjectName("console_chathist_token_count")
        self.history_token_count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )

        self.history_token_count = QLabel("0", self.console_overlay)
        self.history_token_count.setObjectName("console_chathist_token_count")
        self.history_token_count.setToolTip('Session\'s "Chat History" total Tokens count')
        self.history_token_count.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )

        layout.addWidget(self._btn_toggle_console)
        layout.addWidget(self.btn_clear)
        layout.addStretch()
        layout.addWidget(self.history_token_count_label)
        layout.addWidget(self.history_token_count)

        # Panneau de console masqué au début
        self.console_output = QPlainTextEdit(self)
        self.console_output.setObjectName("console_output")
        self.console_output.setReadOnly(True)
        self.console_output.setMaximumHeight(150)
        self.console_output.setVisible(False)

    @pyqtSlot(str)
    def _apply_global_css(self, css: str):
        """
        Store current CSS and re-render all existing bubbles through the worker
        so that rendered HTML is generated with the active theme.
        """
        self._current_css = css  # keep for future rendered bubbles

        # If no bubbles map yet, nothing to re-render
        if not hasattr(self, "_bubbles_by_index"):
            return

        # For each known bubble, try to re-render using its stored raw_markdown
        # (we rely on the fact that the QFrame parent has property "raw_markdown").
        for message_id, tb in list(self._bubbles_by_index.items()):
            try:
                if tb is None:
                    continue
                frame = tb.parentWidget()
                if frame is None:
                    continue
                raw = frame.property("raw_markdown")
                if raw and isinstance(raw, str) and raw.strip():
                    # Re-render via existing mechanism (thread-safe)
                    self._enqueue_render(raw, message_id)
                else:
                    # Fallback: if there's no raw markdown, reapply stylesheet wrapper
                    try:
                        html = tb.toHtml()

                        html = re.sub(r"<style>.*?</style>", "", html, flags=re.DOTALL)
                        final_html = f"<html><head><meta charset='utf-8'><style>{css}</style></head><body>{html}</body></html>"
                        tb.setHtml(final_html)
                    except Exception:
                        pass
            except Exception as e:
                print("ERROR in _apply_global_css for message", message_id, ":", e)

    def _toggle_console_output(self, checked: bool):
        self.console_output.setVisible(checked)
        self.btn_clear.setVisible(checked)
        self.history_token_count_label.setVisible(checked)
        self._btn_toggle_console.setText("▲" if checked else "▼")
        # changer une propriété Qt pour
        self.console_overlay.setProperty("console_visible", checked)
        self.console_overlay.style().unpolish(self.console_overlay)
        self.console_overlay.style().polish(self.console_overlay)

        if checked:
            y = self.console_overlay.height()
            self.console_output.setGeometry(2, y, self.width() - 4, 150)
            self.console_output.raise_()  # pour être au-dessus du contenu

    def _position_console_overlay(self):
        """Positionne le bandeau collé en haut"""
        self.console_overlay.setGeometry(2, 2, self.width() - 4, self.console_overlay.height())

    def update_token_counter(self):
        """Calculate and displays the total of tokens in the current session."""
        total_tokens = 0
        for i in range(self.history_layout.count()):
            bubble = self.history_layout.itemAt(i).widget()
            if bubble:
                text_widget = bubble.findChild(QTextBrowser)
                if text_widget:
                    try:
                        text = text_widget.toPlainText()
                        total_tokens += self.ctx_parser.count_tokens_from_text(text)
                    except Exception as e:
                        print("Error when counting tokens :", e)

        self.history_token_count.setText(f"{total_tokens}")

    def _emit_message(self, text: str):
        """Emits the user_message signal for Mainwindow."""
        if text:
            self.user_message.emit(text)

    def show_stop_button(self):
        self._btn_stop.show()
        self._reposition_stop_button()

    def hide_stop_button(self):
        self._btn_stop.hide()

    def _handle_stop_clicked(self):
        self.stop_requested.emit()  # connection à MainWindow
        self._batch_render_timer.stop()
        self.hide_stop_button()

    def set_session_id(self, session_id: int):
        self.current_session_id = session_id

    def create_bubble(self) -> QTextBrowser:
        """Creates a QTextBrowser stylized to display text in a bubble (user and llm).
        the callers append_*_bubble() manage the parent, insertion, identification and resizing
        """
        tb = QTextBrowser()
        tb.setObjectName("chatText")
        tb.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)

        def show_browser_menu(pos: QtCore.QPoint):
            menu = tb.createStandardContextMenu()
            menu.setObjectName("chatTextMenu")
            menu.exec(tb.mapToGlobal(pos))

        tb.customContextMenuRequested.connect(show_browser_menu)
        tb.setContentsMargins(0, 0, 0, 0)
        # capter Ctrl+Wheel même lorsqu'on survole la bulle
        tb.installEventFilter(self)
        tb.setFont(self.history_area.font())
        # cadre transparent
        tb.setFrameShape(QFrame.Shape.NoFrame)
        # pas de scroll interne
        tb.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tb.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # wrapping
        tb.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        tb.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        # interaction
        flags = (
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        tb.setTextInteractionFlags(flags)
        # size policy: expanding horizontal, fixed vertical => hauteur fixée plus tard
        tb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # tb.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        tb.setMinimumHeight(1)  # pour permettre le redimensionnement auto
        # autoriser le focus au clic pour le scroll avec pageup/pagedown
        tb.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        tb.viewport().installEventFilter(self)
        # les bulles créées héritent automatiquement du dernier CSS stylisé par le thème
        if hasattr(self, "_current_css"):
            tb.document().setDefaultStyleSheet(self._current_css)

        def _bubble_wheelEvent(ev):
            # Ctrl+Wheel -> on veut toujours zoomer (l'eventFilter le gère)
            if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return super(tb.__class__, tb).wheelEvent(ev)
            # sinon -> forward à la QScrollArea
            # on cible directement la viewport pour le scroll vertical
            QApplication.sendEvent(self.history_scroll.viewport(), ev)

        tb.wheelEvent = _bubble_wheelEvent  # bind sur l'instance

        avail = self.history_scroll.viewport().width() - 20
        tb.setMaximumWidth(avail)

        return tb

    def append_user_bubble(self, message: str, message_id: int | None = None) -> None:
        """Displays a user message."""
        is_new_message = message_id is None
        if is_new_message:
            msg = self.session_manager.add_message(self.current_session_id, "user", message)
            message_id = int(msg.id)
        bubble = QFrame()
        # capter la molette si on survole la bordure
        bubble.installEventFilter(self)
        bubble.setProperty("bubbleType", "user")
        bubble.setProperty("message_id", message_id)
        bubble.setProperty("raw_markdown", message)
        bubble.setObjectName("userBubble")
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        tb = self.create_bubble()  # style identique avec bubbleType user
        tb.setObjectName("chatText")
        tb.setProperty("bubbleType", "user")
        tb.mouseDoubleClickEvent = lambda ev: self._set_active_bubble_and_overlay(bubble)

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tb)
        self.history_layout.addWidget(bubble)

        avail = self.history_scroll.viewport().width() - 20
        tb.setMaximumWidth(avail)

        self._bubbles_by_index[message_id] = tb
        self._enqueue_render(message, message_id)

        # Ajouter le spinner uniquement si c'est un nouveau message
        if is_new_message:
            spinner = create_spinner(text="Processing...", object_name="stream_spinner")
            self.history_layout.addWidget(spinner)
            self.llm_waiting_widget = spinner

    def append_llm_bubble(self, message: str, message_id: int | None = None) -> None:
        """Displays an already complete LLM message for rendering."""
        if self.current_session_id is None:
            raise ValueError("No session_id defined in Chatpanel.")
        if message_id is None:
            msg = self.session_manager.add_message(self.current_session_id, "llm", message)
            message_id = int(msg.id)
        # 1) créer et insérer QFrame + QTextBrowser
        bubble = QFrame()
        # capter la molette si on survole la bordure
        bubble.installEventFilter(self)
        bubble.setProperty("bubbleType", "llm")
        bubble.setProperty("message_id", message_id)
        bubble.setProperty("raw_markdown", message)
        bubble.setObjectName("llmBubble")
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        tb = self.create_bubble()
        tb.setObjectName("chatText")
        tb.setProperty("bubbleType", "llm")
        tb.setPlainText(message)
        tb.mouseDoubleClickEvent = lambda ev: self._set_active_bubble_and_overlay(bubble)

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tb)
        self.history_layout.addWidget(bubble)

        # 2) stocker pour le worker
        self._bubbles_by_index[message_id] = tb

        # 3) lancer la conversion markdown -> HTML via RendererWorker de renderer_thread
        self._enqueue_render(message, message_id)

    # ======= STREAMING ENTRY POINT ===

    def _begin_llm_stream(self) -> QTextBrowser:
        """
        Creates a bubble **streaming** (QFrame + QTextBrowser),
        with the same appearance as a history LLM bubble, then locks its width.
        """
        return self.start_streaming_llm_bubble()

    def start_streaming_llm_bubble(self, message_id: int | None = None) -> None:
        """
        Initializes a new LLM bubble for streaming and returns the QTextBrowser.
        -> Called on the first chunk received. any first chunk calls _begin_llm_stream(),
        that does just `return self.start_streaming_llm_bubble()`.
        """
        self.llm_streaming_started = False

        self._apply_deferred_bubble_adjustments()
        # 1) forcer la finalisation de l'ancienne bulle
        if self.llm_bubble_widget:
            # Injecte le rendu final de ce qui était streamé
            self._enqueue_render(self._stream_buffer, self._current_render_message_id)
            self.llm_bubble_widget = None

        # 2) Récupération d'un nouvel ID si besoin
        if message_id is None:
            try:
                msg = self.session_manager.add_message(self.current_session_id, "llm", "")
                message_id = int(msg.id)
            except Exception:
                raise RuntimeError("start_streaming_llm_bubble() called without message id.")

        # 3) Création du cadre + QTextBrowser
        bubble = QFrame()
        bubble.setProperty("bubbleType", "llm")
        bubble.setProperty("message_id", message_id)
        bubble.setObjectName("llmBubble")
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bubble.installEventFilter(self)

        tb = self.create_bubble()
        tb.setProperty("bubbleType", "llm")
        tb.setHtml("<p></p>")  # html vide au départ pour éviter fallback de setPlainText("")
        tb.installEventFilter(self)
        tb.viewport().installEventFilter(self)

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tb)

        # 4) Enregistrement pour la suite du streaming
        self.history_layout.addWidget(bubble)
        self.llm_bubble_widget = tb
        self._current_render_message_id = message_id
        self._bubbles_by_index[message_id] = tb

        # -> Verrouillage immédiat **avant** d'insérer du texte
        avail = self.history_scroll.viewport().width() - 20
        bubble.setMaximumWidth(avail)

        self._stream_buffer = ""

        # Démarrer la minuterie de batch rendering
        # elle continue de fonctionner jusqu'à .stop() dans gui._on_llm_response_complete
        self._batch_render_timer.start()

        # 5) déclenchez un relayout global tout de suite
        self._update_bubble_widths()
        self._adjust_bubble_height(bubble, tb)
        # 6) Scroll en bas
        QTimer.singleShot(0, self._force_scroll_to_bottom)

        return tb

    def _kill_spinner(self):
        w = getattr(self, "llm_waiting_widget", None)
        if not w:
            return
        try:
            if hasattr(w, "stop_spinner"):
                w.stop_spinner()
            else:
                w.hide()
                self.history_layout.removeWidget(w)
                w.deleteLater()
        finally:
            self.llm_waiting_widget = None

    def update_streaming_llm_bubble(self, chunk: str) -> None:
        """
        Add chunk to the content of the bubble during streaming scheduling a throttled render.
        Adjusts its height size, keeping the width.
        """
        # ajout du bouton "stop" pendant le streaming
        if not self.llm_streaming_started:
            self.show_stop_button()
            self.llm_streaming_started = True
            if self.llm_waiting_widget:
                # supprimer le spinner d'attente "processing..."
                self._kill_spinner()

        if not self.llm_bubble_widget:
            # pas d'init -> on démarre
            self.start_streaming_llm_bubble()

        tb = self.llm_bubble_widget
        bubble = tb.parentWidget()

        # 1) Verrouillage de la largeur
        avail = self.history_scroll.viewport().width() - 20
        if avail != self._last_bubble_width:
            self._last_bubble_width = avail
            tb.setFixedWidth(avail)
            bubble.setFixedWidth(avail)
            self._adjust_bubble_height(bubble, tb)

        # 2) Accumuler le markdown brut
        self._stream_buffer += chunk  # buffer local

        # 4) recalcul manuel de la hauteur
        doc = tb.document()
        # On garde la largeur figée aavec tb.viewport().width()
        doc.setTextWidth(tb.viewport().width())
        height = doc.size().height()
        tb.setFixedHeight(int(height) + 2)
        bubble.setFixedHeight(
            int(height + bubble.contentsMargins().top() + bubble.contentsMargins().bottom() + 2)
        )

        # 5) Forcer le relayout de tout le chat
        if not self._bubble_update_timer.isActive():
            self._bubble_update_timer.start()

        sb = self.history_scroll.verticalScrollBar()
        if sb.value() >= sb.maximum() - 30 and self.auto_scroll_enabled:
            QTimer.singleShot(0, self._scroll_to_bottom)
        elif not self.auto_scroll_enabled and hasattr(self, "_frozen_scroll_value"):
            QTimer.singleShot(0, lambda: sb.setValue(self._frozen_scroll_value))

    def _flush_batch_render(self):
        """accumulated markdown rendering after the Debounce period."""
        if not self._stream_buffer or not self.llm_bubble_widget:
            # Rien à rendre - ca arrive si le timer se déclenche avant que le premier morceau arrive
            # (un flux très rapide qui se termine avant 150 ms).
            return
        # Rendu du markdown accumulé
        self._enqueue_render(self._stream_buffer, self._current_render_message_id)

    def _apply_deferred_bubble_adjustments(self):
        """
        Only adjusts the height of each bubble (QTextBrowser + QFrame)
        referenced in _bubbles_by_index, without invalidating the general layout.
        Remove the entries whose widgets have been destroyed.
        """
        to_remove = []
        for message_id, tb in list(self._bubbles_by_index.items()):
            # 1) Si le widget ou son parent n'existe plus, on le supprime de la map
            try:
                if tb is None or tb.parentWidget() is None:
                    to_remove.append(message_id)
                    continue
            except RuntimeError:
                # Le widget a été détruit côté C++, on le purge
                to_remove.append(message_id)
                continue

            frame = tb.parentWidget()  # QFrame parent de tb

            self._adjust_bubble_height(frame, tb)

        # 6) Nettoyer les entrées obsolètes
        for mid in to_remove:
            del self._bubbles_by_index[mid]

    def append_message(self, sender: str, message: str, message_id: int | None = None) -> None:
        """Call the suitable function according to the sender (user ou llm)."""
        if self.current_session_id is None:
            raise ValueError("No session_id defined in Chatpanel.")
        if sender.lower() == "user":
            self.append_user_bubble(message, message_id)
        else:
            self.append_llm_bubble(message, message_id)

    def _enqueue_render(self, markdown_text: str, index: int):
        """
        Calls the RendererWorker in its QThread to convert
        markdown_text (string) in HTML, associated with index.
        """
        # Utilise QMetaObject.invokeMethod pour appeler de façon thread-safe
        QMetaObject.invokeMethod(
            self._renderer_worker,
            "process",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, markdown_text),
            Q_ARG(int, index),
        )

    def _onRenderedHtml(self, html: str, index: int):
        """
        Slot called in the main thread when the rendering is finished.
        index corresponds to the message_id (or internal index) to know
        which widget to update.
        Injects HTML, then resizes precisely the bubble.
        """
        widget = self._bubbles_by_index.get(index)
        if widget is None:
            print("no widget")
            return  # Peut arriver si la bulle a été supprimée entre-temps

        # Récupérer le QFrame parent
        bubble = widget.parentWidget()
        if not isinstance(bubble, QFrame):
            print("no bubble")
            return

        # 1) Verrouille la largeur de la bulle
        avail = self.history_scroll.viewport().width() - 20
        bubble.setMaximumWidth(avail)
        widget.setMaximumWidth(avail)
        # 2) Met à jour le HTML dans le QTextBrowser
        # Appliquer CSS en préfixant le HTML rendu avec un bloc <style>.
        css = getattr(self, "_current_css", "")
        if css:
            # Envelopper le HTML (html ici est le fragment renvoyé par Renderer)
            final_html = (
                f"<html><head><meta charset='utf-8'>{css}</head><body>{html}</body></html>"
            )
        else:
            final_html = html

        widget.clear()
        widget.setHtml(final_html)

        # 3) forcer le wrapping à la largeur fixe
        doc = widget.document()
        # on utilise widget.viewport().width() pour exclure d'éventuelles bordures
        doc.setTextWidth(widget.viewport().width())

        # 4) recalculer la hauteur manuellement
        self._adjust_bubble_height(bubble, widget)

        # 5) scroll si on est tout en bas
        sb = self.history_scroll.verticalScrollBar()
        if sb.value() >= sb.maximum() - 30 and self.auto_scroll_enabled:
            QTimer.singleShot(0, self._scroll_to_bottom)

        # 6) En fin de streaming, forcer le recalcul du layout global
        # self.llm_streaming_started = False
        if self.llm_bubble_widget:
            bubble = self.llm_bubble_widget.parentWidget()
            bubble.setProperty("streaming", False)

        QTimer.singleShot(0, self._refresh_history_layout)
        QTimer.singleShot(0, self.update_token_counter)

    def _onRenderError(self, errmsg: str, index: int):
        """
        If the renderer has encountered an error, can display a message
        leaving a "rendering error" in the bubble.
        """
        widget = self._bubbles_by_index.get(index)
        if not widget:
            return
        widget.setHtml(f"<i style='color:red;'>Erreur de rendu : {errmsg}</i>")

    def set_default_font_size(self, size: int):
        """Updates the default police size (clamped)
        Then apply to the chat history and resize all the bubbles."""
        # 1) Clampage
        size = min(self._max_font_size, max(self._min_font_size, size))
        self._default_font_size = size

        # 2) Appliquer à history_area & input
        font = self.history_area.font()
        font.setPointSize(size)
        font.setBold(False)
        for w in (self.history_area, self.input):
            w.setFont(font)

        # 3) Mettre à jour chaque bulle existante
        for tb in self.history_area.findChildren(QTextBrowser):
            bubble = tb.parentWidget()
            if isinstance(bubble, QFrame):
                tb.setFont(font)
                self._adjust_bubble_height(bubble, tb)

    def _adjust_bubble_height(self, bubble: QFrame, tb: QTextBrowser):
        """
        Adjust the height of TB and its parent bubble according to text/HTML content, without internal scroll.
        """
        # 1) Forcer le wrapping du document à la largeur actuelle de tb
        doc = tb.document()
        doc.setTextWidth(tb.viewport().width())

        # 2) Calculer la hauteur du contenu
        content_h = doc.size().height()

        # 3) Appliquer la hauteur au QTextBrowser
        tb.setFixedHeight(int(content_h) + 2)  # +2 pour pti padding

        # 4) Appliquer la hauteur au QFrame parent
        margins = bubble.contentsMargins()
        total_h = content_h + margins.top() + margins.bottom() + 2
        bubble.setFixedHeight(int(total_h))

    def _adjust_bubble_widths(self):
        """
        Adjust the maximum width of the bubbles and the internal QTextBrowser without fixing absolute width.
        """
        avail = self.history_scroll.viewport().width() - 20
        if getattr(self, "_last_bubble_width", None) == avail:
            return
        self._last_bubble_width = avail
        for bubble in self.history_area.findChildren(QFrame):
            bubble.setMaximumWidth(avail)
            tb = bubble.findChild((QTextBrowser, QTextEdit))
            if tb:
                inner = avail - (
                    bubble.layout().contentsMargins().left()
                    + bubble.layout().contentsMargins().right()
                )
                tb.setMaximumWidth(inner)

    def _update_bubble_widths(self):
        """Sets the max width of each bubble's QTextBrowser to prevent horizontal scroll"""
        # On prend la largeur dispo dans le viewport, moins un peu de marge
        available = self.history_scroll.viewport().width() - 20
        if self._last_bubble_width == available:
            return
        self._last_bubble_width = available
        for bubble in self.history_area.findChildren(QFrame):
            bubble.setMaximumWidth(available - 2)
        for lbl in self.history_area.findChildren(QTextBrowser):
            lbl.setMaximumWidth(available - 10)  # un peu de marge intérieure

    def resizeEvent(self, event):
        """When the panel changes size, the Width Max of Bubbles are readjusted."""
        # Stocker le ratio pour restauration
        self._saved_scroll_ratio = self._get_scroll_ratio()
        self.history_scroll.setUpdatesEnabled(False)
        super().resizeEvent(event)
        # gérer l'overlay de console
        self._position_console_overlay()
        if self.console_output.isVisible():
            y = self.console_overlay.height()
            self.console_output.setGeometry(5, y, self.width() - 5, 150)
        # gérer les autres overlays (boutons copie/edit/delete et stop LLM response)
        self._reposition_overlays()
        self._reposition_stop_button()

        self._refresh_bubble_layout()

        # renable scroll
        QTimer.singleShot(0, lambda: self.history_scroll.setUpdatesEnabled(True))
        QTimer.singleShot(0, self._refresh_after_zoom)

    def _refresh_bubble_layout(self):
        """
        Recalculates the sizes of the bubbles in height and width.
        Called by resizeEvent or Mainwindow.resizeEvent after resizing.
        """
        # 1) recalculer hauteur de chaque bulle pour le nouveau wrapping
        for bubble in self.history_area.findChildren(QFrame):
            tb = bubble.findChild(QTextBrowser)
            if tb:
                self._adjust_bubble_height(bubble, tb)
        # 2) puis layout largeurs
        self._adjust_bubble_widths()

    def _refresh_history_layout(self):
        """
        Recalculates the sizes of the bubbles (when not streaming) and adjusts the total height of the chat.
        """
        # Pour chaque bulle (QFrame), on laisse Qt ajuster sa taille selon son contenu
        for frame in self.history_area.findChildren(QFrame):
            tb = frame.findChild(QTextBrowser)
            if tb:
                self._adjust_bubble_height(frame, tb)

    def _get_scroll_ratio(self):
        # Sauvegarde précise de la position relative
        scrollbar = self.history_scroll.verticalScrollBar()
        scroll_max = scrollbar.maximum()
        scroll_value = scrollbar.value()

        # Calcul du ratio de position (0 = haut, 1 = bas)
        if scroll_max > 0:
            scroll_ratio = scroll_value / scroll_max
        else:
            scroll_ratio = 0
        return scroll_ratio

    def _handle_ctrl_wheel_zoom(self, event: QWheelEvent) -> bool:
        """handles ctrl+wheel event to keep scroll position when zooming"""
        event.accept()  # Bloque la propagation du scroll vertical

        scroll_ratio = self._get_scroll_ratio()

        # Calcul de la nouvelle taille de police
        delta = event.angleDelta().y()
        new_size = self._default_font_size + (1 if delta > 0 else -1)
        new_size = max(self._min_font_size, min(self._max_font_size, new_size))
        if new_size == self._default_font_size:
            return True  # limite atteinte -> ne rien faire

        self._default_font_size = new_size

        # Appliquer la police
        font = self.input.font()
        font.setPointSize(new_size)
        self.input.setFont(font)

        for tb in self.history_area.findChildren(QTextBrowser):
            f = tb.font()
            f.setPointSize(new_size)
            tb.setFont(f)
        for ed in self.history_area.findChildren(QTextEdit):
            f = ed.font()
            f.setPointSize(new_size)
            ed.setFont(f)

        # Mise à jour des tailles avec temporisation
        self._adjust_bubble_widths()
        QTimer.singleShot(2, self._refresh_after_zoom)

        # Stocker le ratio pour restauration
        self._saved_scroll_ratio = scroll_ratio
        return True

    def _refresh_after_zoom(self):
        """Update bubbles size after a change of police"""
        for bubble in self.history_area.findChildren(QFrame):
            widget = bubble.findChild(QTextBrowser) or bubble.findChild(QTextEdit)
            if widget:
                self._adjust_bubble_height(bubble, widget)

        # Restaurer la position relative
        QTimer.singleShot(10, self._restore_scroll_position)

    def _restore_scroll_position(self):
        """Restore the scrolling position after update"""
        if hasattr(self, "_saved_scroll_ratio"):
            scrollbar = self.history_scroll.verticalScrollBar()
            new_max = scrollbar.maximum()
            new_value = int(self._saved_scroll_ratio * new_max)
            scrollbar.setValue(new_value)

    def _scroll_to_bottom(self):
        """Handles automatic scrolling when streaming LLM's answer
        if scrolling is at max position (auto_scroll_enabled)
        """
        if not self.auto_scroll_enabled:
            return
        QTimer.singleShot(0, self._force_scroll_to_bottom)

    def _force_scroll_to_bottom(self):
        """Streaming with automatic scrolling if auto scroll enabled <=> scroll near the max (bottom)"""
        scrollbar = self.history_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_scroll(self, value: int):
        """Manages the scrolling state (auto_scroll_enabled or _frozen_scroll_value)"""
        # print("Scroll détecté, valeur :", value)
        self._reposition_overlays()
        self._reposition_stop_button()
        scrollbar = self.history_scroll.verticalScrollBar()
        buffer = 15
        at_bottom = value >= scrollbar.maximum() - buffer
        self.auto_scroll_enabled = at_bottom
        if not at_bottom:
            self._frozen_scroll_value = value

    def _set_active_bubble_and_overlay(self, bubble: QFrame):
        """Handles the showing/hiding switch of bubbles buttons (copy/edit/delete)"""
        if self._active_bubble and self._active_bubble == bubble:
            self._btn_copy.clicked.disconnect()
            self._btn_edit.clicked.disconnect()
            self._btn_delete.clicked.disconnect()
            self._btn_copy.hide()
            self._btn_edit.hide()
            self._btn_delete.hide()
            self._active_bubble = None
            return
        self._active_bubble = bubble
        message_id = bubble.property("message_id")
        if message_id is None:
            print("Error: the bubble does not have a message_id!")
            return  # Ne pas activer l'overlay si l'ID n'est pas valide
        self._activate_overlay()

    def _activate_overlay(self):
        """Handles connection/display of bubble buttons (copy/edit/delete) to the _active_bubble"""
        # Déconnexion propre des signaux
        try:
            self._btn_copy.clicked.disconnect()
            self._btn_edit.clicked.disconnect()
            self._btn_delete.clicked.disconnect()
        except Exception:
            pass

        if not self._active_bubble:
            return

        is_user = self._active_bubble.property("bubbleType") == "user"
        message_id = self._active_bubble.property("message_id")

        if message_id is None:
            print("Error: the active bubble does not have a message_id!")
            return

        self._btn_copy.clicked.connect(lambda: self._copy_bubble(self._active_bubble, message_id))
        self._btn_edit.clicked.connect(
            lambda: self._start_edit(self._active_bubble, is_user, message_id)
        )
        self._btn_delete.clicked.connect(
            lambda: self._delete_bubble(self._active_bubble, message_id)
        )

        self._reposition_overlays()
        self._btn_copy.show()
        self._btn_edit.show()
        self._btn_delete.show()

    def _reposition_overlays(self, _=None):
        """Reposition the buttons in the Viewport, aligned at the bottom right of the bubble, at the Y of click."""
        # Si la bulle a été supprimée ou n'existe plus, on cache tout
        bubble = self._active_bubble
        try:
            # Vérifier si la bulle est toujours valide
            if not bubble or bubble.parent() is None:
                raise RuntimeError

            # Vérification si la bulle est visible dans le viewport
            vp = self.history_scroll.viewport()
            tl = self._active_bubble.mapTo(vp, QPoint(0, 0))
            if tl.y() + self._active_bubble.height() < 0 or tl.y() > vp.height():
                # Bulle hors de vue, on cache les boutons
                self._btn_copy.hide()
                self._btn_edit.hide()
                self._btn_delete.hide()
                return

            # La bulle est visible, on affiche et repositionne les boutons
            bubble_right = tl.x() + self._active_bubble.width()
            margin = 4
            x = bubble_right - self._btn_edit.width() - margin
            y = tl.y() + self._active_bubble.height() - self._btn_edit.height() - margin
            y = max(margin, min(y, vp.height() - self._btn_edit.height() - margin))
            self._btn_delete.move(int(x), int(y))
            self._btn_edit.move(int(x) - self._btn_edit.width() - margin, int(y))
            self._btn_copy.move(
                int(x) - self._btn_edit.width() - self._btn_copy.width() - margin - margin, int(y)
            )

            # Afficher les boutons
            self._btn_copy.show()
            self._btn_edit.show()
            self._btn_delete.show()

        except RuntimeError:
            # widget déjà détruit
            self._btn_copy.hide()
            self._btn_edit.hide()
            self._btn_delete.hide()
            self._active_bubble = None

    def _reposition_stop_button(self):
        """Dynamically position the Stop button in the Viewport when streaming."""
        if not self._btn_stop.isVisible():
            # print("debug : _reposition_stop_button skipped (not visible)")
            return
        viewport = self.history_scroll.viewport()
        x = viewport.width() - self._btn_stop.width() - 16
        y = viewport.height() - self._btn_stop.height() - 16
        # print(f"debug : move to x={x}, y={y}")
        self._btn_stop.move(x, y)
        self._btn_stop.raise_()

    def _start_edit(self, bubble: QFrame, is_user: bool, message_id: int):
        """Pass the bubble in Inline edition mode, by editing the source Markdown."""
        message_id = bubble.property("message_id")
        if message_id is None:
            print("Bubble without message_id! Properties:", bubble.dynamicPropertyNames())
            return

        # Récupère le text_widget du QTextBrowser et le HTML existant
        text_widget = bubble.findChild(QTextBrowser)

        if text_widget is None:
            print("No qtextbrowser found in the bubble")
            return

        label_style = text_widget.styleSheet()
        # Markdown brut
        original_md = bubble.property("raw_markdown") or ""
        # Style et marges d'origine
        bubble_style = bubble.styleSheet()
        margins = bubble.layout().contentsMargins()

        # Largeur disponible
        avail = self.history_scroll.viewport().width() - 20

        # Création du cadre d'édition
        edit_frame = QFrame()
        edit_frame.setProperty("bubbleType", bubble.property("bubbleType"))
        edit_frame.setProperty("message_id", message_id)
        edit_frame.setProperty("raw_markdown", original_md)
        edit_frame.setStyleSheet(bubble_style)
        edit_frame.setObjectName("userBubble" if is_user else "llmBubble")
        edit_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        edit_layout = QVBoxLayout(edit_frame)
        edit_layout.setContentsMargins(margins)
        edit_layout.setSpacing(4)

        # Zone de texte (plain Markdown source)
        editor = QTextEdit()
        editor.setPlainText(original_md)
        # editor.setFont(self.history_area.font())
        font = editor.font()
        font.setPointSize(self._default_font_size)
        editor.setFont(font)
        if label_style:
            editor.setStyleSheet(label_style)
        editor.setObjectName("chatText")
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        editor.setMaximumWidth(avail - 10)
        editor.setMinimumWidth(avail - 10)
        edit_layout.addWidget(editor)

        # Boutons Modifier / Annuler
        btns_layout = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("bouton_edit_annuler")
        spacer1 = QWidget(self)
        spacer1.setObjectName("spacer1_wdg")
        spacer1.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        btn_modify = QPushButton("Save")
        btn_modify.setObjectName("bouton_edit_modifier")
        btns_layout.addWidget(btn_cancel)
        btns_layout.addWidget(spacer1)
        btns_layout.addWidget(btn_modify)
        edit_layout.addLayout(btns_layout)

        # Remplacer la bulle existante par edit_frame
        idx = self.history_layout.indexOf(bubble)
        self.history_layout.takeAt(idx)
        bubble.setParent(None)
        self._edit_original_bubble = bubble
        self.history_layout.insertWidget(idx, edit_frame)

        # desactiver les boutons pendant l'edition (éviter doublons en cascade)
        self._btn_copy.hide()
        self._btn_edit.hide()
        self._btn_delete.hide()
        # Escape pour "Annuler"
        shortcut_cancel = QShortcut(QKeySequence("Escape"), edit_frame)
        # Ctrl+S pour "Enregistrer"
        shortcut_save = QShortcut(QKeySequence("Ctrl+S"), edit_frame)
        # Connexions
        btn_cancel.clicked.connect(lambda: self._cancel_edit(edit_frame, bubble))
        shortcut_cancel.activated.connect(lambda: self._cancel_edit(edit_frame, bubble))
        btn_modify.clicked.connect(
            lambda: self._confirm_edit(edit_frame, message_id, editor.toPlainText(), is_user)
        )
        shortcut_save.activated.connect(
            lambda: self._confirm_edit(edit_frame, message_id, editor.toPlainText(), is_user)
        )

        # Ajuster dynamiquement hauteur texte+boutons
        def resize_edit():
            # hauteur texte
            doc_height = int(editor.document().size().height())
            h_btn = btns_layout.sizeHint().height()
            edit_frame.setFixedHeight(doc_height + h_btn + 40)

        QTimer.singleShot(0, resize_edit)

    def _confirm_edit(self, edit_frame: QFrame, message_id: int, new_text: str, is_user: bool):
        """
        Record the modification (new_text in raw) in DB,
        Remove the editing frame, then reconstructs the bubble to the exact index.
        """
        # Mise à jour en base du texte brut
        self.session_manager.update_message(message_id, new_text)

        # Repérer l'indice de l'edit_frame et le supprimer
        idx = self.history_layout.indexOf(edit_frame)
        self.history_layout.takeAt(idx)
        edit_frame.deleteLater()
        # Supprimer définitivement la référence à la bulle d’origine
        if hasattr(self, "_edit_original_bubble") and self._edit_original_bubble:
            self._edit_original_bubble.deleteLater()
            self._edit_original_bubble = None

        # Créer la nouvelle bulle (QFrame + BubbleTextBrowser)
        bubble = QFrame()
        bubble.setProperty("bubbleType", "user" if is_user else "llm")
        bubble.setProperty("message_id", message_id)
        bubble.setProperty("raw_markdown", new_text)
        bubble.setObjectName("userBubble" if is_user else "llmBubble")
        bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Texte dans la bulle
        tb = self.create_bubble()
        tb.setObjectName("chatText")
        tb.setProperty("bubbleType", "user" if is_user else "llm")
        tb.setPlainText(new_text)
        tb.mouseDoubleClickEvent = lambda ev: self._set_active_bubble_and_overlay(bubble)

        # Ajout au layout du QFrame
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tb)

        # Insérer la bulle **au même indice**
        self.history_layout.insertWidget(idx, bubble)

        # Mettre à jour le mapping pour la conversion asynchrone future
        self._bubbles_by_index[message_id] = tb
        self._enqueue_render(new_text, message_id)
        # réactiver les boutons
        self._btn_copy.show()
        self._btn_edit.show()
        self._btn_delete.show()
        # Ajuster la taille de la bulle à son contenu
        QTimer.singleShot(0, lambda: self._adjust_bubble_height(bubble, tb))

    def _cancel_edit(self, edit_frame: QFrame, original_bubble: QFrame):
        """Cancels the modification of the Bubble"""
        idx = self.history_layout.indexOf(edit_frame)
        self.history_layout.takeAt(idx)
        edit_frame.deleteLater()
        # Si un « original_bubble » a été stocké, l’utiliser pour réinsertion
        if hasattr(self, "_edit_original_bubble") and self._edit_original_bubble:
            original_bubble = self._edit_original_bubble
            self._edit_original_bubble = None

        self.history_layout.insertWidget(idx, original_bubble)
        # réactiver les boutons
        self._btn_copy.show()
        self._btn_edit.show()
        self._btn_delete.show()

    def _copy_bubble(self, bubble: QFrame, message_id: int):
        """
        Copies the raw Markdown associated with a bubble to the clipboard.
        """
        msg = bubble.property("raw_markdown") or ""

        if not msg:
            print("No Markdown available in this bubble.")
            return

        # Copier dans le presse-papiers
        clipboard: QClipboard = QApplication.clipboard()
        clipboard.setText(msg, mode=QClipboard.Mode.Clipboard)

    def _delete_bubble(self, bubble: QFrame, message_id: int):
        """Removes the bubble and the line from the Database."""
        reply = QMessageBox.question(
            self, "Delete message", "Do you really want to delete this message?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.session_manager.delete_message(message_id)
            idx = self.history_layout.indexOf(bubble)
            if idx >= 0:
                # `takeAt` renvoie un QLayoutItem; on récupère le widget et on le delete
                layout_item = self.history_layout.takeAt(idx)
                widget_to_remove = layout_item.widget()
                if widget_to_remove:
                    widget_to_remove.setParent(None)  # détacher du parent
                    widget_to_remove.deleteLater()  # suppression

            # Nettoyer la table de mapping
            if message_id in self._bubbles_by_index:
                del self._bubbles_by_index[message_id]

        self._btn_copy.hide()
        self._btn_edit.hide()
        self._btn_delete.hide()
        self._active_bubble = None

    def clear_history(self):
        # supprimer widgets
        while self.history_layout.count():
            item = self.history_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        # remettre à zéro maps & flags
        self._bubbles_by_index.clear()
        self.llm_streaming_started = False
        self.llm_bubble_widget = None
        self._stream_buffer = ""
        self.auto_scroll_enabled = True

        # repositionner le scroll proprement
        sb = self.history_scroll.verticalScrollBar()
        sb.setValue(0)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def eventFilter(self, obj, event):
        """
        Intercept CTRL+wheel to manage the zoom for the text
        and prevents the parasitic vertical scroll.
        Otherwise, pass the other events (including wheel only).
        """
        if event.type() == QEvent.Type.Wheel:
            ctrl_held = event.modifiers() & Qt.KeyboardModifier.ControlModifier

            # Ctrl+molette -> zoom texte (bloque complètement le défilement)
            if ctrl_held:
                self._block_wheel_scroll = True
                QTimer.singleShot(200, lambda: setattr(self, "_block_wheel_scroll", False))
                self._handle_ctrl_wheel_zoom(event)
                return True  # Bloque complètement l'événement

            if self._block_wheel_scroll:
                return True  # Bloque le défilement résiduel

            # Molette normale -> mise à jour de l'auto-scroll
            scrollbar = self.history_scroll.verticalScrollBar()
            buffer = 30
            previous = self.auto_scroll_enabled
            self.auto_scroll_enabled = scrollbar.value() >= scrollbar.maximum() - buffer
            if not self.auto_scroll_enabled and previous:
                # print("Scroll manuel détecté -> auto-scroll désactivé")
                self._frozen_scroll_value = scrollbar.value()
            return False  # laisser propager l'event normal

        # Intercepter PgUp / PgDown émis depuis une bulle (QTextBrowser) ou sa viewport
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_PageUp,
            Qt.Key.Key_PageDown,
        ):
            # si l'input a le focus, laisser l'input gérer PgUp/PgDown naturellement
            if self.input.hasFocus():
                return False

            # remonter les parents pour savoir si l'événement vient
            # d'une bulle / du viewport de la bulle / de la zone d'historique
            w = obj
            in_history = False
            while w is not None:
                if (
                    isinstance(w, QTextBrowser)
                    or w is self.history_area
                    or w is self.history_scroll
                    or w is self.history_scroll.viewport()
                ):
                    in_history = True
                    break
                w = w.parent()

            if in_history:
                # Déplacer directement la scrollbar de l'historique (évite de réinjecter l'événement
                # et donc toute récursion vers eventFilter)
                bar = self.history_scroll.verticalScrollBar()
                step = bar.pageStep() or max(1, bar.singleStep() * 10)
                if event.key() == Qt.Key.Key_PageUp:
                    bar.setValue(max(bar.minimum(), bar.value() - step))
                else:
                    bar.setValue(min(bar.maximum(), bar.value() + step))
                return True

        # Tous les autres événements sont traités normalement
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._refresh_history_layout)

    def moveEvent(self, event):
        self.history_scroll.setUpdatesEnabled(False)
        super().moveEvent(event)
        QTimer.singleShot(0, lambda: self.history_scroll.setUpdatesEnabled(True))

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for ChatPanel.
        CTRL+F launches SearchDialog box"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_F:
            selected_text = self._get_selected_text() or ""

            if self.search_dialog is None:
                self.search_dialog = SearchDialog(chat_panel=self, parent=self)
                # calculer position au-dessus du chatpanel
                panel_geo = self.geometry()  # rectangle du chatpanel
                global_pos = self.mapToGlobal(panel_geo.topLeft())
                x = global_pos.x() - 200

                if global_pos.y() > 0:
                    y = max(
                        0, global_pos.y() - self.search_dialog.sizeHint().height() - 5
                    )  # juste au-dessus
                else:
                    y = min(0, global_pos.y() - self.search_dialog.sizeHint().height() - 5)
                self.search_dialog.move(x, y)

            # mettre à jour le texte et appliquer (gère à la fois l'existant et le nouveau)
            self.search_dialog.open_and_search(selected_text)

            self.search_dialog.show()
            self.search_dialog.raise_()
            self.search_dialog.activateWindow()

        else:
            super().keyPressEvent(event)

    # ==== SEARCH BOX
    def _get_selected_text(self) -> str | None:
        """Return the currently selected text in any bubble, or None."""
        for tb in self._bubbles_by_index.values():
            selected = tb.textCursor().selectedText()
            if selected.strip():  # ignore sélection vide ou espaces
                return selected
        return None
