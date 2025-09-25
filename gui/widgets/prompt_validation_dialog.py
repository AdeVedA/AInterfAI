from typing import Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .search_dialog import SearchDialog


class _PromptSearchHelper(QObject):
    """
    Small object that is responsible for intercepting shortcuts Ctrl+F / Esc,
    ope,ning the SearchDialog already existing, and expose get_selected_text()
    for the prompt editing field.
    """

    def __init__(self, parent_dialog: QDialog, edit: QTextEdit):
        super().__init__(parent_dialog)  # le parent = le QDialog
        self.dlg = parent_dialog
        self.edit = edit
        self.search_dialog: Optional[SearchDialog] = None

        # raccourcis
        self._sc_ctrl_f = QShortcut(QKeySequence("Ctrl+F"), self.dlg)
        self._sc_ctrl_f.activated.connect(self._open_search)

        # Esc ferme le SearchDialog sans quitter le prompt dialog
        self._sc_esc = QShortcut(QKeySequence("Escape"), self.dlg)
        self._sc_esc.activated.connect(self._handle_escape)

        # event‑filter pour intercepter les touches du dialog
        self.dlg.installEventFilter(self)

    # Event filter – on laisse Qt gérer le reste (Enter, Ctrl+Enter...)
    def eventFilter(self, watched, event):
        # On ne filtre que les KeyPress du dialog lui‑même
        if watched is self.dlg and event.type() == QEvent.Type.KeyPress:
            # Ctrl+F déjà géré via le QShortcut
            # Esc : si la SearchDialog est visible, on la ferme et on bloque
            # la propagation (pour empêcher le dialog d'interpréter Esc comme Cancel)
            if event.key() == Qt.Key.Key_Escape and self.search_dialog:
                self._close_search()
                return True  # bloquer la propagation
        return super().eventFilter(watched, event)

    # API utilisée par le reste du code
    def get_selected_text(self) -> str | None:
        """Returns the selected text in the QTextEdit, or None."""
        cursor = self.edit.textCursor()
        txt = cursor.selectedText()
        return txt if txt and txt.strip() else None

    # Ouverture / fermeture du SearchDialog
    def _open_search(self):
        """Instanciate (lazy) and shows the Searchdialog above the prompt."""
        if self.search_dialog is None:
            # Le SearchDialog attend un chat_panel avec deux attributs.
            # On crée un mini‑objet qui n'expose que ce dont il a besoin.
            class _FakeChatPanel:
                def __init__(self, edit: QTextEdit):
                    self._bubbles_by_index = {0: edit}
                    self.history_scroll = edit  # QTextEdit est déjà un QAbstractScrollArea

            fake_panel = _FakeChatPanel(self.edit)

            self.search_dialog = SearchDialog(chat_panel=fake_panel, parent=self.dlg)
            self.search_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # prevent from closing
            self.search_dialog.destroyed.connect(self._on_search_destroyed)  # là on gère la fermeture

            if not hasattr(self.search_dialog, "_debounce_timer"):
                self.search_dialog._debounce_timer = QTimer(self.search_dialog)

            self.search_dialog.move(self.dlg.x() + 10, self.dlg.y() - self.search_dialog.sizeHint().height() - 10)

        # passage du texte sélectionné comme requête initiale
        self.search_dialog.open_and_search(self.get_selected_text() or "")
        self.search_dialog.show()
        self.search_dialog.raise_()
        self.search_dialog.activateWindow()

    def _on_search_destroyed(self):
        """Called when the SearchDialog C++ object is really deleted"""
        self.search_dialog = None

    def _handle_escape(self):
        """Closes the Searchdialog if opened"""
        if self.search_dialog:
            self.search_dialog.close()
            self.search_dialog = None
        else:
            # Aucun SearchDialog : fermer le dialogue parent (Send‑Cancel dialog)
            self.dlg.reject()


# la fonction appelée depuis la MainWindow (gui.py)
#
def show_prompt_validation_dialog(self, prompt_text: str) -> Optional[str]:
    """Prompt validation dialog with Ctrl+F integrated search box"""
    dlg = QDialog(self, objectName="config_edit")
    layout = QVBoxLayout(dlg)

    # EDITOR
    edit = QTextEdit(dlg)
    edit.setPlainText(prompt_text)
    edit.setReadOnly(False)
    edit.setFont(self.panel_chat.history_area.font())
    layout.addWidget(edit, 1)

    # Le petit helper qui ajoute la recherche à ce dialog
    dlg._search_helper = _PromptSearchHelper(parent_dialog=dlg, edit=edit)

    # TOKEN COUNT
    token_label = QLabel("0 total request tokens", dlg)
    token_label.setAlignment(Qt.AlignmentFlag.AlignRight)
    token_label.setStyleSheet("color: lightgray; font-size: 12px; margin: 2px 4px 2px 0px;")
    layout.addWidget(token_label, 0, Qt.AlignmentFlag.AlignRight)

    def update_token_count() -> None:
        txt = edit.toPlainText()
        token_label.setText(
            f"{self.message_processor.count_tokens(txt)} total request tokens"
            if txt.strip()
            else "0 total request tokens"
        )

    edit.textChanged.connect(update_token_count)
    update_token_count()

    # BUTTONS
    btn_box = QDialogButtonBox(dlg, objectName="config_edit_btn")
    send_btn = QPushButton("Send (Ctrl+Enter)", dlg)
    send_btn.setObjectName("config_edit_btn_Send")
    send_btn.clicked.connect(dlg.accept)

    cancel_btn = QPushButton("Cancel (Escape)", dlg)
    cancel_btn.setObjectName("config_edit_btn_Cancel")
    cancel_btn.clicked.connect(dlg.reject)

    btn_box.addButton(send_btn, QDialogButtonBox.ButtonRole.ActionRole)
    btn_box.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
    layout.addWidget(btn_box)

    # shortcut (Ctrl+Enter)
    ctrl_enter = QShortcut(QKeySequence("Ctrl+Return"), dlg)
    ctrl_enter.activated.connect(dlg.accept)

    dlg.resize(900, 600)

    # Exécution du dialog
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None

    final_text = edit.toPlainText().strip()
    # print("\n-------final prompt validated------- :\n", final_text)
    return final_text
