from collections import defaultdict

from PyQt6 import QtCore
from PyQt6.QtCore import QByteArray, QEvent, QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from core.models import Folder, Session


class SessionListWidget(QListWidget):
    """List of custom sessions to manage the Drag & Drop in hierarchy."""

    move_to_folder = pyqtSignal(int, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        # Active l'auto-scroll quand on drague près du haut/bas
        self.setAutoScroll(True)
        self.setAutoScrollMargin(20)  # zone de déclenchement de l'autoscroll
        self.verticalScrollBar().setSingleStep(30)  # vitesse d’autoscroll

        self._last_highlight = None
        # === ligne de dépôt ===
        self._drop_line = QFrame(self.viewport())
        self._drop_line.setFrameShape(QFrame.Shape.HLine)
        self._drop_line.setFrameShadow(QFrame.Shadow.Plain)
        self._drop_line.setLineWidth(3)
        # Utilise la couleur de highlight du style
        self._drop_line.setStyleSheet("background-color: palette(highlight); border: white;")
        self._drop_line.hide()
        # mémorise le mode de dépôt pendant le drag
        self._drop_mode = None  # "above", "below" ou None
        self._drop_target = None  # QListWidgetItem sur lequel le drop s’applique

    def startDrag(self, supportedActions):
        """
        Manages the start of the drag (start of the 'move'' operation).
        Create a QMimeData with the selected session ID and launches the drag.
        Args:
            supportedActions: Authorized drag actions (unused there)
        """
        item = self.currentItem()
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        mime = QMimeData()
        mime.setData("application/x-session-id", QByteArray(str(session_id).encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        """
        Manages the entry of an element during Drag.
        Check if the format MIME "application/x-session-id" is valid.
        """
        md = event.mimeData()
        # print(f"dragEnterEvent type: {type(event)}")  # log le type de l'événement
        if md.hasFormat("application/x-session-id"):
            # print("MIME format detected!")
            event.acceptProposedAction()
        else:
            # print("MIME format not detected.")
            event.ignore()

    def dragMoveEvent(self, event):
        """
        Manages the movement of an element during Drag.
        Updates the deposit indicator (highlight) depending on the position.
        """
        md = event.mimeData()
        # Si ce n'est pas notre format, on laisse le parent Qt gérer "normalement"
        if not md.hasFormat("application/x-session-id"):
            return super().dragMoveEvent(event)

        # Highlight personnalisé
        pos = event.position().toPoint()
        idx = self.indexAt(pos)

        # 1. Nettoyer le highlight précédent
        if self._last_highlight:
            self._last_highlight.setProperty("droppable", False)
            self._last_highlight.style().unpolish(self._last_highlight)
            self._last_highlight.style().polish(self._last_highlight)
            self._last_highlight = None

        # 2. Aucun item sous le curseur → ligne viewport (racine) ---
        if not idx.isValid():
            self._drop_line.setGeometry(4, pos.y() - 1, self.viewport().width() - 8, 2)
            self._drop_line.show()
            self._drop_mode = "above"  # on dépose à la racine
            self._drop_target = None
            QAbstractItemView.dragMoveEvent(self, event)
            event.accept()
            return

        # 3. Un item est sous le curseur
        item = self.item(idx.row())
        rect = self.visualRect(idx)  # rectangle de l’item dans le viewport
        top_zone = rect.top() + int(0.10 * rect.height())  # + 10 % du haut
        bottom_zone = rect.bottom() - int(0.10 * rect.height())  # + 10 % du bas

        if pos.y() < top_zone:  # curseur dans la zone haute → INSERT BEFORE
            line_y = rect.top()
            self._drop_mode = "above"
            self._drop_target = item
        elif pos.y() > bottom_zone:  # zone basse → INSERT AFTER
            line_y = rect.bottom()
            self._drop_mode = "below"
            self._drop_target = item
        else:  # zone centrale → on garde le highlight habituel
            self._drop_mode = None
            self._drop_target = item
            self._drop_line.hide()
            # mettre le highlight du widget (déjà fait plus haut)
            w = self.itemWidget(item)
            if w:
                w.setProperty("droppable", True)
                w.style().unpolish(w)
                w.style().polish(w)
                self._last_highlight = w
            QAbstractItemView.dragMoveEvent(self, event)
            event.accept()
            return

        # 4. Afficher la ligne d’insertion
        self._drop_line.setGeometry(4, line_y - 1, self.viewport().width() - 8, 2)
        self._drop_line.show()
        self._drop_target = item  # mémoriser l’item concerné

        # laisser Qt gérer l’autoscroll
        QAbstractItemView.dragMoveEvent(self, event)
        event.accept()

    def dropEvent(self, event):
        """
        Manages the deposit of an element.

        1. Check the MIME format
        2. Determines the target (folder or session)
        3. Emits the signal move_to_folder
        4. Cleans the deposit indicator
        """
        # Vérifier si l'élément glissé contient bien le format MIME attendu
        md = event.mimeData()
        if not md.hasFormat("application/x-session-id"):
            return event.ignore()

        # cache la ligne
        self._drop_line.hide()
        if self._last_highlight:
            self._last_highlight.setProperty("droppable", False)
            self._last_highlight.style().unpolish(self._last_highlight)
            self._last_highlight.style().polish(self._last_highlight)
            self._last_highlight = None

        src_id = int(bytes(md.data("application/x-session-id")).decode())

        # cible par défaut (racine)
        target_folder_id = None
        target_session_id = None

        # on a réellement un item sous le curseur ?
        if self._drop_target:
            widget = self.itemWidget(self._drop_target)
            is_folder = widget.property("isFolder") if widget else False

            if self._drop_mode is None:
                # DROP ON ITEM
                if is_folder:
                    # drop sur le dossier lui‑même  → on veut le mettre dans ce dossier
                    target_folder_id = self._drop_target.data(Qt.ItemDataRole.UserRole)
                else:
                    # drop sur une session → on crée UN NOUVEAU dossier contenant les deux
                    target_folder_id = None
                    target_session_id = self._drop_target.data(Qt.ItemDataRole.UserRole)
            else:
                # DROP BETWEEN ITEMS (above / below)
                # on insère dans le même dossier que l’item cible
                target_folder_id = self._drop_target.data(Qt.ItemDataRole.UserRole + 1)
                target_session_id = None

        # le drop sur soi‑même annule l'évènement (la session reste où elle est)
        if src_id == target_session_id:
            return event.ignore()

        # émission du signal attendu par MainWindow
        self.move_to_folder.emit(src_id, target_folder_id, target_session_id)

        # remise à zéro
        self._drop_mode = None
        self._drop_target = None
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        # cache la ligne
        self._drop_line.hide()
        for i in range(self.count()):
            widget = self.itemWidget(self.item(i))
            if widget:
                widget.setProperty("droppable", False)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
        if self._last_highlight:
            self._last_highlight.setStyleSheet("")
            self._last_highlight = None
        super().dragLeaveEvent(event)


class SessionPanel(QWidget):
    """
    Panel (a): Displays previous sessions in a list and allows creation of a new session.
    Signals:
        session_selected(int): Emitted when a session is chosen.
        new_session(): Emitted when the New Session button is clicked.
        delete_session(int) : émis quand une session est supprimée
    """

    session_selected = pyqtSignal(int)
    new_session = pyqtSignal(object)  # émet int ou None
    session_renamed = pyqtSignal(int, str)  # session_id, session.name
    delete_session = pyqtSignal(int)
    # signaux d'export
    export_markdown_requested = pyqtSignal(object)  # envoi de l'objet session entier
    export_html_requested = pyqtSignal(object)

    new_folder = pyqtSignal(object)  # émet int ou None
    edit_folder = pyqtSignal(int)  # émet folder_id
    folder_renamed = pyqtSignal(int, str)
    delete_folder = pyqtSignal(int)

    def __init__(self, parent=None, session_manager=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 6)
        self.setObjectName("session_panel")
        self.setMinimumWidth(180)
        self.setMaximumWidth(280)
        self.setContentsMargins(0, 0, 0, 0)
        # Titre
        # title = QLabel("Sessions")
        # title.setObjectName("titles")
        # layout.addWidget(title)
        self.session_manager = session_manager
        self.session_items_by_id = {}
        self._expanded_folders: set[int] = set()
        self._first_load = True
        # Filtre actif ("Date", "Prompt-type" ou "LLM")
        self.current_filter = "Date"
        # Bouton de filtre
        filter_layout = QHBoxLayout()
        filter_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filter_btn = QPushButton("Filter : Date", self)
        self.filter_btn.setObjectName("filter_button")
        self.filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_btn.setToolTip(
            "Filter your sessions by :\n- Date(with your folders)\n"
            "- Prompt-type used in session's last message\n- LLM used in session's last message"
        )
        self.filter_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.filter_menu = QMenu(self)
        self.filter_menu.setObjectName("filter_menu")
        self.filter_menu.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_menu.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        for label in ["Date", "Prompt-type", "LLM"]:
            # Créez le widget personnalisé
            widget = QWidget()
            widget_layout = QHBoxLayout(widget)
            widget_layout.setContentsMargins(0, 0, 0, 0)

            label_widget = QLabel(label)
            label_widget.setObjectName("label_filter_menu")
            label_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            label_widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            widget_layout.addWidget(label_widget)

            # Créez l'action avec le widget
            action_widget = QWidgetAction(self.filter_menu)
            action_widget.setDefaultWidget(widget)

            # Connectez le signal
            action_widget.triggered.connect(lambda _, lbl=label: self._apply_filter(lbl))
            self.filter_menu.addAction(action_widget)
        self.filter_btn.setMenu(self.filter_menu)
        # self.filter_menu.setFixedWidth(self.filter_btn.width())
        filter_layout.addWidget(self.filter_btn, Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(filter_layout)

        # Bouton Nouveau dossier
        h = QHBoxLayout()
        self.btn_folder = QPushButton("✚ Folder", self)
        self.btn_folder.setObjectName("session_btn_newfolder")
        self.btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_folder.setContentsMargins(0, 2, 0, 2)
        self.btn_folder.setToolTip("Create a new folder")
        self.btn_folder.clicked.connect(lambda _: self.new_folder.emit(None))
        h.addWidget(self.btn_folder)
        # Bouton nouvelle session
        self.btn_new = QPushButton("✚ Session", self)
        self.btn_new.setObjectName("session_btn_new")
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new.setContentsMargins(0, 2, 0, 2)
        self.btn_new.setToolTip("Create a new session")
        self.btn_new.clicked.connect(lambda _: self.new_session.emit(None))
        h.addWidget(self.btn_new)
        layout.addLayout(h)

        # Liste des sessions
        self.session_list = SessionListWidget(self)
        self.session_list.setObjectName("session_list")
        self.session_list.setAlternatingRowColors(False)
        self.session_list.setAutoFillBackground(False)
        self.session_list.viewport().setAutoFillBackground(False)
        self.session_list.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.session_list.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.session_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.session_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.session_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.session_list.setDropIndicatorShown(True)
        self.session_list.setUniformItemSizes(False)
        layout.addWidget(self.session_list)

        btn_layout = QHBoxLayout()

        # bouton export html
        self.btn_expo_html = QPushButton("📥HTML", self)
        self.btn_expo_html.setObjectName("sess_btn_expo_html")
        self.btn_expo_html.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expo_html.setToolTip("Exports the current session to a HTML file")
        self.btn_expo_html.clicked.connect(self.session_export_html)
        btn_layout.addWidget(self.btn_expo_html)
        # bouton export markdown
        self.btn_expo_md = QPushButton("📥Markdown", self)
        self.btn_expo_md.setObjectName("sess_btn_expo_md")
        self.btn_expo_md.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expo_md.setToolTip("Exports the current session to a markdown file")
        self.btn_expo_md.clicked.connect(self.session_export_markdown)
        btn_layout.addWidget(self.btn_expo_md)

        btn_layout.setContentsMargins(0, 1, 0, 1)
        layout.addLayout(btn_layout)

        # Connexions des signaux
        self.session_list.viewport().installEventFilter(self)
        self.session_list.itemClicked.connect(self._on_item_clicked)
        self.session_list.itemDoubleClicked.connect(self._on_item_renamed)
        self.session_list.currentItemChanged.connect(self._on_current_item_changed)
        self.session_list.move_to_folder.connect(self._handle_move_to_folder)
        # peupler la vue au démarrage (Date fermé par défaut)
        self._expanded_folders.clear()
        folders = self.session_manager.list_folders()
        sessions = self.session_manager.filter_sessions(self.current_filter)
        self.load_sessions(folders, sessions, self.current_filter)
        self._resize_list_items()

    def _create_folder_item(self, folder: Folder) -> QListWidgetItem:
        """
        Create the item and the widget for a folder.
        The widget is stored in item._widget for a fast setItemWidget.
        """
        item = QListWidgetItem()
        # on stocke l'ID du dossier dans UserRole pour le signal click
        item.setData(Qt.ItemDataRole.UserRole, folder.id)

        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_Hover)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.setObjectName("folderRows")
        w.setProperty("sessionRow", True)
        w.setToolTip(folder.name)

        # ON MARQUE LE WIDGET COMME DOSSIER
        w.setProperty("isFolder", True)
        if folder.id >= 1_000_000_000:
            w.setProperty("isHeader", True)

        h = QHBoxLayout(w)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(0)

        if getattr(folder, "isHeader", False) or folder.id >= 1_000_000_000:  # faux dossiers -> catégorie Prompt / LLM
            btn_title = QPushButton(folder.name)
            btn_title.setFlat(True)
            btn_title.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_title.setObjectName("folderTitleLabel")
            btn_title.clicked.connect(lambda _, fid=folder.id: self._toggle_folder(fid))
            btn_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            btn_title.setStyleSheet("text-align: left")
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            h.addWidget(btn_title, 1)
            h.addStretch()
            w.installEventFilter(self)
            item._widget = w
            item.setSizeHint(w.sizeHint())
            return item
        else:  # vrais dossiers -> filtrage Date
            btn = QToolButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setObjectName("btnToggleFolder")
            is_expanded = folder.id in self._expanded_folders
            btn.setArrowType(QtCore.Qt.ArrowType.DownArrow if is_expanded else QtCore.Qt.ArrowType.RightArrow)
            # btn.setText("🞃 " if is_expanded else "🞂 ")
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonFollowStyle)
            btn.clicked.connect(lambda _, fid=folder.id: self._toggle_folder(fid))
            h.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)

            lbl = QLabel(folder.name)
            lbl.setProperty("isFolder", True)
            lbl.setObjectName("folderTitleLabel")
            lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            h.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignLeft)
            h.addStretch()

        # boutons edit / delete (cachés par défaut)
        # btn_edit = QToolButton()
        # btn_edit.setObjectName("btnEditFolder")
        # btn_edit.setText("✏️")
        # btn_edit.setToolTip("Renommer le dossier")
        # btn_edit.clicked.connect(lambda _, fid=folder.id: self.edit_folder.emit(fid))
        # btn_edit.setAutoFillBackground(False)
        # btn_edit.setVisible(False)
        # h.addWidget(btn_edit, alignment=Qt.AlignmentFlag.AlignRight)

        btn_del = QToolButton()
        btn_del.setObjectName("btnDeleteFolder")
        btn_del.setText("🗑️")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn_del.setAutoRaise(True)
        btn_del.setToolTip("Supprimer le dossier")
        btn_del.clicked.connect(lambda _, fid=folder.id: self.delete_folder.emit(fid))
        btn_del.setAutoFillBackground(False)
        btn_del.setVisible(False)
        h.addWidget(btn_del, alignment=Qt.AlignmentFlag.AlignRight)

        w.installEventFilter(self)
        item._widget = w
        item.setSizeHint(w.sizeHint())

        # print(w.sizeHint())  # doit refléter la largeur correcte
        # print(self.session_list.sizeHintForRow(item.row()))  # idem
        return item

    def _create_session_item(self, sess: Session, indent: int = 0) -> QListWidgetItem:
        """
        Create the item and the widget for a session.
        `indent` Allows to shift identation to the right if child of a folder.
        """
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, sess.id)

        # Récupérer le dernier message LLM (ou None)
        last_llm = None
        for m in reversed(sess.messages):
            if m.sender == "llm":
                last_llm = m
                break

        llm_name = last_llm.llm_name if last_llm else ""
        prompt_type = last_llm.prompt_type if last_llm else ""

        w = QWidget()
        w.setObjectName("sessionRows")
        w.setProperty("sessionRow", True)
        w.setAttribute(Qt.WidgetAttribute.WA_Hover)
        # w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.setToolTip(
            f"{sess.session_name}\n"
            f"last message's LLM: {llm_name}\n"
            f"last message's Prompt/Role: {prompt_type}\n"
            f"{sess.created_at.strftime("%Y/%m/%d %H:%M")}"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(indent, 2, 0, 2)
        h.setSpacing(0)  # Réduit l'espacement à 0

        lbl = QLabel(sess.session_name)
        lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        h.addWidget(lbl)
        h.addStretch()

        # boutons edit / delete
        # btn_e = QToolButton()
        # btn_e.setObjectName("btnEditSession")
        # btn_e.setText("✏️")
        # btn_e.setToolTip("Renommer la session")
        # btn_e.setContentsMargins(0, 0, 0, 0)
        # btn_e.clicked.connect(lambda _, sid=sess.id: self.edit_session.emit(sid))
        # btn_e.setVisible(False)
        # h.addWidget(btn_e, alignment=Qt.AlignmentFlag.AlignRight)

        btn_d = QToolButton()
        btn_d.setObjectName("btnDeleteSession")
        btn_d.setText("🗑️")
        btn_d.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_d.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn_d.setAutoRaise(True)
        btn_d.setToolTip("Supprimer la session")
        btn_d.setContentsMargins(0, 0, 0, 0)
        btn_d.clicked.connect(lambda _, sid=sess.id: self.delete_session.emit(sid))
        btn_d.setVisible(False)
        h.addWidget(btn_d, alignment=Qt.AlignmentFlag.AlignRight)

        w.installEventFilter(self)
        item._widget = w
        item.setSizeHint(w.sizeHint())
        return item

    def load_sessions(self, folders: list[Folder], sessions_by_category, filter_type: str | None = None) -> None:
        """
        Loads in self.session_list :
        - filter_type == 'Date' : grouped by folders
        - filter_type in ('Prompt-type','LLM'): grouped by category
        """
        self.session_list.clear()
        # self._expanded_folders.clear()

        # 1) Si c'est le tout premier chargement, on vide _expanded_folders
        if self._first_load:
            self._expanded_folders.clear()
            self._first_load = False

        filter_type = filter_type or self.current_filter

        # == Mode Date ==
        if filter_type == "Date":
            if isinstance(sessions_by_category, list):
                sessions_by_category = {"All": sessions_by_category}
            by_folder = defaultdict(list)
            src = sessions_by_category.get("All", []) if isinstance(sessions_by_category, dict) else sessions_by_category
            for s in src:
                by_folder[s.folder_id].append(s)

            for folder in folders:
                header = self._create_folder_item(folder)
                self.session_list.addItem(header)
                self.session_list.setItemWidget(header, header._widget)

                # Si ce dossier est ouvert, on lui montre ses sessions
                is_open = folder.id in self._expanded_folders

                # crée toutes les sessions, cachées par défaut
                for sess in by_folder.get(folder.id, []):
                    item = self._create_session_item(sess, indent=16)
                    item.setData(Qt.ItemDataRole.UserRole + 1, folder.id)
                    item.setHidden(not is_open)
                    self.session_list.addItem(item)
                    self.session_list.setItemWidget(item, item._widget)

            # sessions à la racine (folder_id None), toujours visibles
            for sess in by_folder.get(None, []):
                item = self._create_session_item(sess, indent=8)
                item.setData(Qt.ItemDataRole.UserRole + 1, None)
                item.setHidden(False)
                self.session_list.addItem(item)
                self.session_list.setItemWidget(item, item._widget)

        # == Mode Prompt/LLM ==
        else:
            for category, sess_list in sessions_by_category.items():
                key = str(category or "Inconnu").strip()
                fake_id = 1_000_000_000 + abs(hash("CAT::" + key))
                folder = Folder(
                    id=fake_id, name=(f"📋 {key.upper()}" if filter_type == "Prompt-type" else f"🤖 {key.upper()}")
                )
                setattr(folder, "isHeader", True)

                header = self._create_folder_item(folder)
                self.session_list.addItem(header)
                self.session_list.setItemWidget(header, header._widget)

                is_open = fake_id in self._expanded_folders
                for sess in sess_list:
                    item = self._create_session_item(sess, indent=8)
                    item.setData(Qt.ItemDataRole.UserRole + 1, fake_id)
                    item.setHidden(not is_open)
                    self.session_list.addItem(item)
                    self.session_list.setItemWidget(item, item._widget)

        for i in range(self.session_list.count()):
            item = self.session_list.item(i)
            folder_id = item.data(Qt.ItemDataRole.UserRole + 1)
            if folder_id is not None and folder_id not in self._expanded_folders:
                item.setHidden(True)
                item._widget.setVisible(False)

        QTimer.singleShot(0, self._resize_list_items)

    def _apply_filter(self, filter_type: str):
        """
        Apply the chosen filter:
        - For 'Date': display by folders and date (via load_ssion with list)
        - For 'prompt': display by prompt_type (via load_ssion with dict)
        - For 'llm': display by llm_name (via load_ssion with dict)
        """
        # 1) Met à jour le texte du bouton
        self.current_filter = filter_type
        self.filter_btn.setText(f"Filter : {filter_type}")

        # 2) Récupère le résultat du filtre (soit list, soit dict)
        result = self.session_manager.filter_sessions(filter_type)

        # 3) Vide la liste actuelle et cache/montre les boutons selon le besoin
        #    On a bien self.session_list (pas clear_session_list)
        self.session_list.clear()
        if filter_type in ("Prompt-type", "LLM"):
            self.btn_folder.setDisabled(True)
            self.btn_new.setDisabled(True)
        else:
            self.btn_folder.setDisabled(False)
            self.btn_new.setDisabled(False)

        # 4) Recharge la vue en passant dossiers + résultat filtré
        #    load_sessions gère à la fois les dict (Prompt/LLM) et les list (Date)
        folders = self.session_manager.list_folders()
        self.load_sessions(folders, result, filter_type)

    def _on_item_clicked(self, item: QListWidgetItem):
        """Recovers the stored ID and emits it."""
        # Ne rien faire si c'est un dossier
        widget = self.session_list.itemWidget(item)
        if widget and widget.property("isFolder"):
            return

        # Sinon, c'est une session : on émet le signal
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id is not None:
            self.session_selected.emit(session_id)

    def _on_current_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        for item in (previous, current):
            if not item:
                continue
            w = getattr(item, "_widget", None)
            if w:
                # retire la classe "selected" de l'ancien
                w.setProperty("selected", item is current)
                w.style().unpolish(w)
                w.style().polish(w)

    def _on_item_renamed(self, item: QListWidgetItem):
        """
        Replaces the Qlabel name (session or folder) with a QLineEdit to allow
        inline edition, then restores a Qlabel and transmits the appropriate signal.
        """
        # 1) Récupère le widget de ligne et le QLabel existant
        widget = self.session_list.itemWidget(item)
        if widget is None:
            return
        lbl: QLabel = widget.findChild(QLabel)
        if lbl is None:
            return

        # 2) Détermine s'il s'agit d'un dossier ou d'une session
        is_folder = lbl.property("isFolder") is True

        # 3) Prépare l'édition inline : supprime le QLabel, ajoute un QLineEdit
        hbox = widget.layout()
        idx = hbox.indexOf(lbl)

        hbox.removeWidget(lbl)
        lbl.deleteLater()

        old_text = lbl.text()
        edit = QLineEdit(widget)
        edit.setObjectName("session_name_edit")
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        edit.setText(old_text)
        edit.selectAll()
        edit.setFocus(Qt.FocusReason.MouseFocusReason)
        if idx >= 0:
            hbox.insertWidget(idx, edit)
        else:
            hbox.addWidget(edit)

        # 4) Quand l'édition est terminée, on gère le commit ou l'annulation
        def finish_edit():
            # Récupérer le nouveau texte
            new_text = edit.text().strip() or old_text

            # 3) Nettoyer le QLineEdit
            edit.deleteLater()

            # 4) Recréer et réinsérer le QLabel
            new_lbl = QLabel(new_text)
            new_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

            if is_folder:
                new_lbl.setProperty("isFolder", True)
            if idx >= 0:
                hbox.insertWidget(idx, new_lbl)
            else:
                hbox.addWidget(new_lbl)
            hbox.addStretch()

            # 5) Forcer Qt à recalculer la taille des lignes
            widget.update()
            self.session_list.updateGeometries()

            # 6) **Puis** émettre le signal de renommage
            if is_folder:
                folder_id = item.data(Qt.ItemDataRole.UserRole)
                self.folder_renamed.emit(folder_id, new_text)
            else:
                session_id = item.data(Qt.ItemDataRole.UserRole)
                self.session_renamed.emit(session_id, new_text)

        edit.editingFinished.connect(finish_edit)

    def _toggle_folder(self, folder_id: int):
        """
        Open/Close a folder (parent session) or a filter category (prompt / LLM).
        """
        open_now = folder_id not in self._expanded_folders
        if open_now:
            self._expanded_folders.add(folder_id)
        else:
            self._expanded_folders.remove(folder_id)

        for i in range(self.session_list.count()):
            item = self.session_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == folder_id:
                # MAJ du bouton toggle dans le widget dossier
                btn = item._widget.findChild(QToolButton, "btnToggleFolder")
                if btn:
                    # btn.setText("🞃 " if open_now else "🞂 ")
                    btn.setArrowType(QtCore.Qt.ArrowType.DownArrow if open_now else QtCore.Qt.ArrowType.RightArrow)
            if item.data(Qt.ItemDataRole.UserRole + 1) == folder_id:
                item.setHidden(not open_now)  # hide when closing, show when opening
                item._widget.setVisible(open_now)

        QTimer.singleShot(0, self._resize_list_items)

    def open_folder(self, folder_id: int):
        """Opens a specific folder if not already opened."""
        if folder_id not in self._expanded_folders:
            self._expanded_folders.add(folder_id)
            folders = self.session_manager.list_folders()
            filtered_sessions = self.session_manager.filter_sessions(self.current_filter)
            self.load_sessions(folders, filtered_sessions, self.current_filter)

    def _handle_move_to_folder(self, session_id: int, folder_id: int, after_session_id: int | None):
        """
        Handler called during a drop. Moves the session, then recharge the list.
        """
        # print(f"debug : Déplacement de la session {session_id} vers dossier {folder_id}, après {after_session_id}")
        # 1. On effectue le déplacement via session_manager
        self.session_manager.move_session_to_folder(session_id, folder_id)

        # 2) Force l'ouverture du dossier cible (si pas None)
        if folder_id is not None:
            # Force l'ouverture du dossier si il est fermé
            self._expanded_folders.add(folder_id)

        # 3) Recharge correctement la liste : folders ET sessions séparément
        folders = self.session_manager.list_folders()
        sessions = self.session_manager.list_sessions()
        self.load_sessions(folders, sessions, self.current_filter)

    def _resize_list_items(self):
        """Resize of the sessions/folders widgets (eventFilter when resizing panel)"""
        list_width = self.session_list.viewport().width()
        for i in range(self.session_list.count()):
            item = self.session_list.item(i)
            w = getattr(item, "_widget", None)
            if w:
                # 1) Largeur = largeur du viewport - marges si besoin
                w.setFixedWidth(list_width - 2)
                # 2) pour les headers, on étire aussi le bouton titre
                btn = w.findChild(QPushButton, "folderTitleLabel")
                if btn:
                    btn.setFixedWidth(list_width - 2)
                # 3) mise à jour du hint
                item.setSizeHint(w.sizeHint())

    def session_export_markdown(self):
        """Get the active session and emits a signal with the complete session object
        for markdown export"""
        item = self.session_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        session = self.session_manager.get_session(session_id)
        if session:
            self.export_markdown_requested.emit(session)

    def session_export_html(self):
        """Get the active session and emits a signal with the complete session object
        html export"""
        item = self.session_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        session = self.session_manager.get_session(session_id)
        if session:
            self.export_html_requested.emit(session)

    def _toggle_buttons(self, widget: QWidget, visible: bool):
        """Displays/masks The Delete buttons only for the widget given."""
        for btn in widget.findChildren(QToolButton, options=Qt.FindChildOption.FindDirectChildrenOnly):
            name = btn.objectName()
            if name in {"btnDeleteSession", "btnDeleteFolder"}:  # "btnEditSession", "btnEditFolder",
                btn.setVisible(visible)

    def eventFilter(self, obj, event):
        """Displays/masks buttons only for the hovered widget."""
        if event.type() == QEvent.Type.HoverEnter:
            if isinstance(obj, QWidget) and obj.property("isHeader") is True:
                return False
            self._toggle_buttons(obj, True)
        elif event.type() == QEvent.Type.HoverLeave:
            self._toggle_buttons(obj, False)
        elif obj == self.session_list.viewport() and event.type() == QEvent.Type.Resize:
            self._resize_list_items()
        return super().eventFilter(obj, event)
