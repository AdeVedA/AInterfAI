import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.context_parser import ParserConfig


class ContextConfigDialog(QDialog):
    """
    QDialog to edit multiple named context parsing configurations stored in JSON.

    Attributes:
        parser: Instance of ParserConfig loaded with JSON configs.
        selected_config_name: Name of the config selected at accept.
    """

    def __init__(self, parent, parser):
        super().__init__(parent)
        self.setObjectName("config_edit")
        self.parser = parser
        self.selected_config_name = parser.config_name
        self.setWindowTitle("Edit Context Configurations")
        self.setMinimumSize(1200, 650)

        self.tabs = QTabWidget()
        tab_bar = self.tabs.tabBar()
        tab_bar.setExpanding(True)
        tab_bar.setUsesScrollButtons(False)
        tab_bar.setDocumentMode(True)
        tab_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tab_bar.setElideMode(Qt.TextElideMode.ElideNone)
        self._build_tabs()

        bb = QDialogButtonBox(self)
        bb.setObjectName("config_edit_btn")
        save_btn = QPushButton("Save")
        save_btn.setObjectName("config_edit_btn_Save")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("config_edit_btn_Cancel")
        restore_btn = QPushButton("Restore defaults")
        restore_btn.setObjectName("config_edit_btn_RestoreDefaults")
        bb.addButton(save_btn, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        bb.addButton(restore_btn, QDialogButtonBox.ButtonRole.ResetRole)

        save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.reject)
        restore_btn.clicked.connect(self.restore_defaults)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        # layout.addWidget(btn_add)
        layout.addWidget(bb)

    def _build_tabs(self):
        """Clear and rebuild tabs from parser._cfg_dict"""
        self.tabs.clear()
        self.widgets = {}
        for name, content in self.parser._cfg_dict.get("configs", {}).items():
            self._add_tab(name, content)
        # select active
        names = list(self.parser._cfg_dict["configs"].keys())
        if self.parser.config_name in names:
            idx = names.index(self.parser.config_name)
            self.tabs.setCurrentIndex(idx)

        btn_add = QPushButton("➕ Add Config")
        btn_add.setObjectName("config_edit_btn_add")
        btn_add.clicked.connect(self._add_new_tab)
        self.tabs.setCornerWidget(btn_add, Qt.Corner.TopRightCorner)

    def _add_tab(self, name: str, content: dict):
        tab = QWidget()
        tab.setObjectName("ConfigFormContainer")
        vbox = QVBoxLayout(tab)

        hbox = QHBoxLayout()
        name_label = QLabel("Configuration Name : ")
        name_label.setObjectName("config_tab_name")
        name_edit = QLineEdit(name)
        name_edit.setObjectName("config_tab_name_ed")
        name_edit.setPlaceholderText("Configuration name")
        name_edit.textChanged.connect(
            lambda text, t=tab: self.tabs.setTabText(self.tabs.indexOf(t), text)
        )
        hbox.addWidget(name_label)
        hbox.addWidget(name_edit)
        vbox.addLayout(hbox)

        text_edit = QTextEdit()
        text_edit.setObjectName("config_tab_text_ed")
        text_edit.setPlainText(json.dumps(content, indent=2))

        vbox.addWidget(text_edit)
        self.tabs.addTab(tab, name)
        self.widgets[name] = (name_edit, text_edit)

    def _add_new_tab(self):
        base = "new_config"
        idx = 1
        names = set(self.parser._cfg_dict.get("configs", {}).keys())
        while f"{base}_{idx}" in names:
            idx += 1
        self._add_tab(f"{base}_{idx}", {})

    def _on_save(self):
        new_configs = {}
        # iterate tabs
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            name_edit, text_edit = tab.findChildren((QLineEdit, QTextEdit))
            name = name_edit.text().strip()
            text = text_edit.toPlainText()
            if not name:
                QMessageBox.warning(self, "Error", "Configuration name cannot be empty.")
                return
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as e:
                QMessageBox.warning(self, "JSON Error", f"Invalid JSON in '{name}': {e}")
                return
            new_configs[name] = parsed

        # update parser dict and save
        self.parser._cfg_dict["configs"] = new_configs
        # determine selected
        self.selected_config_name = self.tabs.tabText(self.tabs.currentIndex())
        self.parser.config_name = self.selected_config_name
        self.parser.save()
        self.accept()

    def restore_defaults(self) -> None:
        """Restore default values for the currently active configuration tab."""
        current_index = self.tabs.currentIndex()
        if current_index < 0 or current_index >= len(self.tab_widgets):
            return

        current_tab = self.tab_widgets[current_index]
        config_name = self.config_names[current_index]

        # Récupération des valeurs par défaut depuis ParserConfig
        defaults = ParserConfig.get_default_config(config_name)

        # Mise à jour des champs dans le widget
        current_tab.set_values(defaults)

    def select_config(self, name: str):
        """Programmatically select a tab by name."""
        names = [self.tabs.tabText(i) for i in range(self.tabs.count())]
        if name in names:
            self.tabs.setCurrentIndex(names.index(name))
