from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class SearchHighlighter(QSyntaxHighlighter):
    """
    QSyntaxHighlighter for highlighting all occurrences of a pattern in a QTextDocument.
    The highlighter draws both the regular matches (yellow) and the current match (white)
    without ever modifying the QTextDocument itself
    """

    def __init__(self, document, pattern=""):
        super().__init__(document)
        self.pattern = pattern
        self.matches = []  # liste de (start, length) absolute in document
        self.current_global = None  # le start absolu du current match ou None

    def set_pattern(self, pattern):
        """Set pattern and recompute matches (called from the dialog)"""
        self.pattern = pattern
        self.matches = []
        self.current_global = None
        # rehighlight appelle highlightBlock et rebuild self.matches
        self.rehighlight()

    def highlightBlock(self, text):
        """Called by Qt for each text block. We compute matches and paint them"""
        # vider les matches au début d'un rehighlight complet (1er block)
        if self.currentBlock().position() == 0:
            # reconstruire from scratch
            self.matches = []

        if not self.pattern:
            return

        block_pos = self.currentBlock().position()
        # boucle avec .find (c + rapide pour les recherches littérales)
        pat = self.pattern
        start_idx = 0
        plen = len(pat)
        while True:
            idx = text.find(pat, start_idx)
            if idx == -1:
                break
            global_start = block_pos + idx
            self.matches.append((global_start, plen))

            fmt = QTextCharFormat()
            if self.current_global == global_start:
                fmt.setBackground(QColor("#ffff2b"))  # yellow for current
            else:
                fmt.setBackground(QColor("#00c0b0"))  # water for others
            self.setFormat(idx, plen, fmt)

            start_idx = idx + plen

    def set_current_global(self, start):
        """
        Set which absolute start is the current match (or None to clear).
        Then rehighlight only this document (efficient)
        """
        self.current_global = start
        # rehighlight va repeindre les blocs et utiliser current_global pour choisir la couleur
        self.rehighlight()

    def clear_highlight(self):
        """Clear everything done by this highlighter"""
        self.set_pattern("")  # reset matches et rehighlights


class SearchDialog(QDialog):
    """
    Search dialog for ChatPanel using QSyntaxHighlighter.
    Highlights all matches in yellow, current in white
    """

    def __init__(self, chat_panel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search in chat")
        self.setObjectName("searchDialog")
        # Tool -> au dessus de fenêtre parent, frameless -> sans bordures # (, ...stay on top)
        # Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlag(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.chat_panel = chat_panel

        # widgets
        self.search_field = QLineEdit(self)
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText("Search... (min. 3 characters)")
        self.search_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.label = QLabel("", self)
        self.label.setObjectName("searchLabel")

        self.prev_btn = QPushButton("< Prev", self)
        self.prev_btn.setObjectName("searchPrevButton")
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(self._go_prev)

        self.next_btn = QPushButton("Next >", self)
        self.next_btn.setObjectName("searchNextButton")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(self._go_next)

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setObjectName("searchCloseButton")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFixedSize(15, 15)
        self.close_btn.setToolTip("Close search")
        self.close_btn.clicked.connect(self.close)

        # inner container layout
        self._container = QFrame(self)  # pour dans le container tous les lier
        self._container.setObjectName("searchContainer")
        container_layout = QHBoxLayout(self._container)
        container_layout.setContentsMargins(6, 4, 6, 2)
        container_layout.setSpacing(6)
        # partie de gauche
        container_layout.addWidget(self.search_field, 1)
        # partie de droite
        btn_box = QHBoxLayout()
        btn_box.setSpacing(4)
        btn_box.addWidget(self.prev_btn)
        btn_box.addWidget(self.next_btn)
        btn_box.addStretch()
        btn_box.addWidget(self.close_btn, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        right_box = QVBoxLayout()
        right_box.setSpacing(2)
        right_box.addLayout(btn_box)
        right_box.addWidget(self.label)

        container_layout.addLayout(right_box)

        # met le container en tant que seul widget du dialog
        dlg_layout = QVBoxLayout(self)
        dlg_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(self._container)

        # state
        self.highlighters = {}  # bubble_id -> SearchHighlighter
        self.matches = []  # liste de tuples (bubble, start, length, highlighter)
        self.current_index = -1

        # debounce
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._apply_search)
        # un flag sur le débounce
        # self._debounce_alive = True

        self.search_field.textChanged.connect(self._on_text_changed)

    # SIGNALS
    def _on_text_changed(self, text):
        self._debounce_timer.start(300)  # 300 ms de debounce

    def open_and_search(self, text: str):
        """
        Set the search_field to `text` and force an immediate search.
        Works reliably even for multiple successive Ctrl+F.
        """
        if text is None:
            text = ""

        # stop debounce pour éviter les appels multiples
        if self._debounce_timer.isActive():
            self._debounce_timer.stop()

        # clear old highlighters pour éviter qu'ils restent
        self._clear_all_highlights()

        # mettre à jour le champ texte
        self.search_field.setText(text)  # déclenche textChanged

        # forcer l'application immédiate de la recherche
        self._apply_search()

    # SEARCH + CACHE
    def _apply_search(self):
        """Apply search: compute matches only if search text changed, keep HTML/CSS intact."""
        search_text = self.search_field.text()

        # si texte vide -> clear highlights et retour
        if not search_text or len(search_text.strip()) < 3:
            self._clear_all_highlights()
            self.label.setText("")
            return

        # nouvelle recherche -> clear tout
        self._clear_all_highlights()

        # reconstruire matches en créant / mettant à jour les highlighters
        for message_id, tb in self.chat_panel._bubbles_by_index.items():
            # réutiliser l'objet highlighter if present, sinon on en crée un
            highlighter = self.highlighters.get(message_id)
            if highlighter is None:
                highlighter = SearchHighlighter(tb.document(), search_text)
                # set_pattern() appellera Rechighlight via le constructeur mais on reste explicite
                highlighter.set_pattern(search_text)
                self.highlighters[message_id] = highlighter
            else:
                highlighter.set_pattern(search_text)

            # append to matches à partir de ce highlighter
            for start, length in highlighter.matches:
                self.matches.append({"bubble": tb, "start": start, "length": length, "highlighter": highlighter})

        self._last_search_text = search_text

        # Focus premier résultat
        if self.matches:
            self.current_index = 0
            self._highlight_current()

        # update label
        match = "matches" if len(self.matches) > 1 else "match"
        self.label.setText(f"{self.current_index + 1 if self.matches else 0}/{len(self.matches)} {match} found")

    def _clear_all_highlights(self):
        """Clear all highlights and reset cache. Perform a one-time manual cleanup of any leftover formats"""
        # Clear via highlighters
        for h in self.highlighters.values():
            try:
                h.clear_highlight()
            except Exception:
                # defensive: ignore if highlighter est en mauvais état
                pass

        # Nettoyage manuel & ponctuel des éléments résiduels de mergeCharFormat provenant d'un ancien code
        # (on fait cette opération une seule fois par session de searchdialog pr éviter les ralentissements)
        if not getattr(self, "_manual_cleanup_done", False):
            for tb in self.chat_panel._bubbles_by_index.values():
                doc = tb.document()
                cursor = QTextCursor(doc)
                cursor.beginEditBlock()
                cursor.select(QTextCursor.SelectionType.Document)
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(0, 0, 0, 0))  # transparent
                cursor.mergeCharFormat(fmt)
                cursor.endEditBlock()
            self._manual_cleanup_done = True

        # finally clear our maps & cache
        self.highlighters.clear()
        self.matches.clear()
        self.current_index = -1
        self._prev_highlight_info = None

    # NAVIGATION
    def _highlight_current(self):
        """Highlight current match (via highlighters) and scroll exactly to it"""
        if not (0 <= self.current_index < len(self.matches)):
            return

        # previous et current info
        prev = getattr(self, "_prev_highlight_info", None)
        prev_highlighter = prev["highlighter"] if prev is not None else None
        # prev_start = prev["start"] if prev is not None else None

        match_info = self.matches[self.current_index]
        tb = match_info["bubble"]
        start = match_info["start"]
        # length = match_info["length"]
        curr_highlighter = match_info["highlighter"]

        # Update highlighters: nettoyer les prev current marker, et set new one.
        # on rehighlight seulement les documents impliqués.
        if prev_highlighter is curr_highlighter:
            # meme document: juste mettre current_global à new start
            curr_highlighter.set_current_global(start)
        else:
            # differents documents: nettoyer prev et set curr
            if prev_highlighter is not None:
                prev_highlighter.set_current_global(None)
            curr_highlighter.set_current_global(start)

        # mettre la selection du QTextCursor sur la cible QTextBrowser (pour visibilité)
        cursor = tb.textCursor()
        cursor.setPosition(start)  # point d'insertion
        # cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        tb.setTextCursor(cursor)  # curseur pour le scrolling

        # s'assurer que le match rect est visible dans le QTextBrowser
        QTimer.singleShot(0, tb.ensureCursorVisible)

        # on s'assure que la bulle est visible dans le viewport history_scroll,
        # en mappant le match_rect au scroll viewport et en ajustant la scrollbar.
        bubble_widget = tb.parentWidget()
        if bubble_widget:
            scroll_area = self.chat_panel.history_scroll
            viewport = scroll_area.viewport()
            match_rect = tb.cursorRect(cursor)
            if not viewport.isAncestorOf(tb):
                # on est dans le contexte de "prompt_validation_dialog"
                global_pos = tb.mapToGlobal(match_rect.topLeft())
            else:
                # mapper le top-left du match rect des coordonnées du tb au viewport
                global_pos = tb.mapTo(viewport, match_rect.topLeft())
            scroll_bar = scroll_area.verticalScrollBar()
            # centrer le viewport autour du match
            new_value = scroll_bar.value() + global_pos.y() - (viewport.height() // 2)
            # Régler à la plage valide
            if new_value < scroll_bar.minimum():
                new_value = scroll_bar.minimum()
            elif new_value > scroll_bar.maximum():
                new_value = scroll_bar.maximum()
            scroll_bar.setValue(int(new_value))

        # Store pour la prochaine itération
        self._prev_highlight_info = match_info

        # mettre à jour "current/total"
        self.label.setText(f"{self.current_index + 1}/{len(self.matches)} matches found")

    def _go_next(self):
        """Jump to next occurrence."""
        if not self.matches:
            return
        self.current_index = (self.current_index + 1) % len(self.matches)
        self._highlight_current()

    def _go_prev(self):
        """Jump to previous occurrence."""
        if not self.matches:
            return
        self.current_index = (self.current_index - 1) % len(self.matches)
        self._highlight_current()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    # CLEANUP
    def closeEvent(self, event):
        """Clear highlights and reset cache when dialog closes.
        Also release ChatPanel reference."""
        # detacher highlighters pour la fermeture
        for h in self.highlighters.values():
            try:
                h.setDocument(None)  # detacher pour que highlightBlock ne crashe pas
            except Exception:
                pass
        # nettoyage
        self._clear_all_highlights()
        # ChatPanel -> reinitialise à None la searchbox
        if hasattr(self.chat_panel, "search_dialog"):
            self.chat_panel.search_dialog = None
        super().closeEvent(event)
