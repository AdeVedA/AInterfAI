from typing import Any, Union

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextOption
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)


class ModelDiffDialog(QDialog):
    """
    edit_mode = True:
        Shows a table with fields for ONE model, fields can be edited and sent back (to record in DB).
    edit_mode = false :
        Shows a table with all changed fields for all models.
        Caller passes the list of dicts produced by LLMPropertiesManager.sync_missing_and_refresh().
    Returns a list of field names that the user wants to apply.
    """

    def __init__(self, diffs: Union[list[dict], dict], edit_mode: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit model properties" if edit_mode else "Refresh properties for all models")
        self.setMinimumSize(1400, 950)
        if isinstance(diffs, dict):  # on a passé un SEUL modèle (edit_mode)
            model_name = diffs.get("model_name", "")
            diff_tuple: dict[str, tuple[Any, Any]] = {k: (v, v) for k, v in diffs.items() if k != "model_name"}
            diffs = [{"model": model_name, "diff": diff_tuple}]
        else:
            pass
        self.diffs = diffs
        self.edit_mode = edit_mode
        self.MAX_HEIGHT = 110
        self.parent = parent

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        intro_layout = QHBoxLayout()
        info_lbl = QLabel(
            "Some Ollama LLM properties differ from the values stored in the database. "
            "Check the following boxes you want to update."
            if not self.edit_mode
            else "Edit the values below and press `Apply` when finished."
        )

        none_tooltip = "Show new values that are `None`"
        none_title = QLabel("Display rows with `None` new values : ")
        none_title.setToolTip(none_tooltip)
        none_title.setProperty("qssClass", "slider-value")
        self.none_checkbox = QCheckBox()
        self.none_checkbox.setObjectName("config_flash_attent")
        self.none_checkbox.setToolTip(none_tooltip)
        self.none_checkbox.setProperty("qssClass", "slider-value")
        intro_layout.addWidget(info_lbl, alignment=Qt.AlignmentFlag.AlignLeft)
        intro_layout.addStretch()
        if not self.edit_mode:
            intro_layout.addWidget(none_title, alignment=Qt.AlignmentFlag.AlignRight)
            intro_layout.addWidget(self.none_checkbox, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(intro_layout)

        row_number = sum(len(d.keys()) for d in self.diffs) if not self.edit_mode else sum(len(d["diff"]) for d in self.diffs)

        self.table = QTableWidget(row_number, 5)
        self.table.setObjectName("modelDiffTable")
        labels = (
            ["Update?", "Model", "Field", "Current (DB)", "New (Ollama)"]
            if not self.edit_mode
            else ["Update?", "Model", "Field", "Current (DB)", "New"]
        )
        self.table.setHorizontalHeaderLabels(labels)
        self.table.setCornerButtonEnabled(True)
        self.table.setSortingEnabled(True)

        hdr = self.table.horizontalHeader()
        hdr.setObjectName("diffHeader")
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # checkbox
        self.table.setColumnWidth(0, 69)  # colonne checkbox largeur fixe
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Model name
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Field name
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Current value
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # New value
        hdr.setStretchLastSection(False)

        v_hdr = self.table.verticalHeader()
        v_hdr.setObjectName("rowNumbers")
        v_hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        # v_hdr.setVisible(False) # pour cacher la 1ère colonne d'index

        layout.addWidget(self.table)
        # cacher la colonne “Model” quand on est en mode edit
        if self.edit_mode:
            self.table.setColumnHidden(1, True)

        row = 0
        # print("DEBUG self.diffs = ", self.diffs)
        for model_diff in self.diffs:
            model_name = model_diff["model"]
            fields = model_diff["diff"]
            # print("DEBUG fields : (value, value) : ", fields)
            for field, (old, new) in fields.items():
                # colonne 0 : checkbox
                chk = QCheckBox()
                chk.setObjectName(f"chk_{row}_{field}")
                chk.setChecked(False)
                # chk.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setCellWidget(row, 0, chk)

                # colonne 1 : model name
                lbl_model = QLabel(model_name)
                lbl_model.setObjectName("modelCell")
                lbl_model.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                lbl_model.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

                # colonne 2 : field name
                lbl_field = QLabel(field)
                lbl_field.setObjectName("fieldCell")
                lbl_field.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                lbl_field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

                # colonne 3 : valeur actuelle BDD
                txt_cur = QTextEdit()
                txt_cur.setPlainText(str(old))
                txt_cur.setReadOnly(True)
                txt_cur.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
                txt_cur.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
                txt_cur.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                txt_cur.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                txt_cur.setMaximumHeight(self.MAX_HEIGHT if not self.edit_mode else 800)
                txt_cur.setMinimumHeight(0)
                txt_cur.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                txt_cur.setObjectName("diffValues")

                # colonne 4 : nouvelle valeur (Ollama en multi refresh ou User en model edit_mode)
                txt_new = QTextEdit()
                txt_new.setPlainText(str(new))
                txt_new.setReadOnly(not self.edit_mode)
                txt_new.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
                txt_new.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
                txt_new.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                txt_new.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                txt_new.setMaximumHeight(self.MAX_HEIGHT if not self.edit_mode else 800)
                txt_new.setMinimumHeight(0)
                txt_new.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                txt_new.setObjectName("diffValues")

                txt_new.rawValue = new  # garder la valeur row pour update

                # items cachés pour classement
                # colonne 1 – model name  (alphabetique)
                itm_model = QTableWidgetItem()
                itm_model.setData(Qt.ItemDataRole.DisplayRole, model_name)  # str
                self.table.setItem(row, 1, itm_model)

                # colonne 2 – field name  (alphabetique)
                itm_field = QTableWidgetItem()
                itm_field.setData(Qt.ItemDataRole.DisplayRole, field)  # str
                self.table.setItem(row, 2, itm_field)

                # colonne 3 – current value (numerique / texte)
                cur_item = QTableWidgetItem()
                cur_item.setData(
                    Qt.ItemDataRole.DisplayRole,
                    old if isinstance(old, (int, float)) else str(old),
                )
                self.table.setItem(row, 3, cur_item)

                # colonne 4 – new value (numerique / texte)
                new_item = QTableWidgetItem()
                new_item.setData(
                    Qt.ItemDataRole.DisplayRole,
                    new if isinstance(new, (int, float)) else str(new),
                )
                self.table.setItem(row, 4, new_item)

                # mettre les CellWidgets au dessus des items
                self.table.setCellWidget(row, 1, lbl_model)
                self.table.setCellWidget(row, 2, lbl_field)
                self.table.setCellWidget(row, 3, txt_cur)
                self.table.setCellWidget(row, 4, txt_new)

                # hauteur pour ces rows
                txt_cur.document().setTextWidth(self.table.columnWidth(3))
                txt_new.document().setTextWidth(self.table.columnWidth(4))
                cur_h = int(txt_cur.document().size().height())
                new_h = int(txt_new.document().size().height())
                # mettre une taille max pour l'affichage initial (longs templates)
                max_value_height = max(cur_h, new_h)
                needed_height = min(self.MAX_HEIGHT if not self.edit_mode else 800, max_value_height)
                self.table.setRowHeight(row, needed_height)
                # tailles redimensionnables
                txt_cur.setMaximumHeight(16777215)
                txt_new.setMaximumHeight(16777215)
                txt_cur.setMinimumHeight(0)
                txt_new.setMinimumHeight(0)
                row += 1

        # bouttons
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Apply")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)

        layout.addLayout(btn_box)

        if not self.edit_mode:
            # connection de la checkbox
            self.none_checkbox.stateChanged.connect(self._refresh_none_rows)
            # apply the initial filter (checkbox is unchecked by default)
            self._refresh_none_rows()

    def _refresh_none_rows(self):
        """Show all rows when the checkbox is checked,
        otherwise if unchecked hide every row when "New (Ollama)" cell holds None."""
        show_none = self.none_checkbox.isChecked()

        for row in range(self.table.rowCount()):
            # colonne 4 contient le QTextEdit qu'on a créé plus tôt
            widget = self.table.cellWidget(row, 4)

            # récupérer la valeur typée d'origine qu'on a enregistré dans le widget.rawValue
            if isinstance(widget, QTextEdit) and hasattr(widget, "rawValue"):
                new_val = widget.rawValue
            else:
                # fallback – traiter toute string empty/“None” comme None
                item = self.table.item(row, 4)
                txt = item.text() if item else ""
                new_val = None if txt in ("", "None") else txt
            none_pack = ["", "None", "unknown", "Unknown"]
            hide_row = (new_val is None or new_val in none_pack or str(new_val) in none_pack) and not show_none
            self.table.setRowHidden(row, hide_row)

    def selected_fields(self) -> dict[str, dict[str, str]]:
        """Return the field names that the user ticked."""
        models_fields: dict[str, dict[str, str]] = {}

        for row in range(self.table.rowCount()):
            chk: QCheckBox = self.table.cellWidget(row, 0)
            if not chk.isChecked():
                continue

            # colonne 1 = model name
            w_model = self.table.cellWidget(row, 1)
            model = w_model.text() if isinstance(w_model, QLabel) else ""
            # colonne 2 = field name
            w_field = self.table.cellWidget(row, 2)
            field = w_field.text() if isinstance(w_field, QLabel) else ""
            # colonne 4 = new value
            widget = self.table.cellWidget(row, 4)
            if isinstance(widget, QTextEdit) and hasattr(widget, "rawValue"):
                new_value = widget.rawValue  # int / float / list / …
            elif isinstance(widget, QTextEdit):
                new_value = widget.toPlainText()  # fallback
            else:
                item = self.table.item(row, 4)
                new_value = item.text() if item else ""

            # construire le dico de dicos
            if model not in models_fields:
                models_fields[model] = {}
            models_fields[model][field] = new_value

        return models_fields

    def get_edited_fields(self) -> dict[str, any]:
        """
        Returns a flat `{field_name: typed_value}` dict for the single model being edited.
        Raises `ValueError` if a conversion fails.
        """
        if not self.edit_mode:
            raise RuntimeError("get_edited_fields() is only valid in edit mode")

        result: dict[str, any] = {}

        # types python attendus – les garder synchro avec les colonnes de LLMProperties
        type_map = {
            # "size": float,
            "context_length": int,
            # "capabilities": list,  # JSON‑encoded list
            "temperature": float,
            "top_k": float,
            "repeat_penalty": float,
            "top_p": float,
            "min_p": float,
            # "architecture": str,
            # "parameter_size": str,
            # "quantization_level": str,
            "template": str,
        }

        for row in range(self.table.rowCount()):
            chk: QCheckBox = self.table.cellWidget(row, 0)
            if not chk.isChecked():
                continue
            # colonne 2 : field name
            w_field = self.table.cellWidget(row, 2)
            if not w_field:
                continue
            field = w_field.text()

            widget = self.table.cellWidget(row, 4)  # QTextEdit valeur editée
            raw_text = widget.toPlainText().strip()
            if raw_text in ("", "None"):
                value = None
            else:
                expected_type = type_map.get(field, str)

                try:
                    if expected_type is int:
                        value = int(raw_text)
                    elif expected_type is float:
                        value = float(raw_text)
                    # elif expected_type is list:
                    #     import json
                    #     # permettre soit JSON string soit liste Python literal
                    #     parsed = json.loads(raw_text) if raw_text else []
                    #     if not isinstance(parsed, list):
                    #         raise ValueError
                    #     value = parsed
                    # elif expected_type is str and isinstance(widget, QTextEdit) and hasattr(widget, "rawValue"):
                    #     value = widget.rawValue
                    # elif isinstance(widget, QTextEdit):
                    #     value = widget.toPlainText()  # fallback
                    else:
                        value = raw_text
                except Exception as exc:
                    raise ValueError(f"Invalid value (should be '{expected_type}') for field '{field}': {raw_text}") from exc

            result[field] = value

        return result
