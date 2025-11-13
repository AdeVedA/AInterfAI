# -*- coding: utf-8 -*-
import functools
import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from core.theme.color_palettes import COLOR_PALETTES
from core.theme.theme_manager import GUI_CONFIG_PATH, get_current_theme, set_current_theme
from gui.model_sync_worker import ModelSyncWorker
from gui.widgets.model_diff_dialog import ModelDiffDialog
from gui.widgets.spinner import create_spinner

from .widgets.status_indicator import create_status_indicator


# ToolBar : System prompt, paramètres LLM, read & update config
class Toolbar(QToolBar):
    """
    Application toolbar containing setup/themes menu, LLM selection, Role selection,
    and toggles for Session, Context and Config panels.
    Signals:
        toggle_llm : Emitted when button "Load LLM" is clicked on
        llm_changed(str): Emitted when the selected LLM changes.
        role_changed(str): Emitted when the selected Role changes.
        new_role(str, str): Emitted when a new Role is defined
        toggle_sessions(bool): Show/hide sessions panel.
        toggle_chat_alone(bool): Show only chat panel/show all panels
        toggle_context(bool): Show/hide context panel.
        toggle_config(bool): Show/hide config panel.
        theme_changed(str): Emitted when theme changed
    """

    toggle_llm = pyqtSignal()
    llm_changed = pyqtSignal(str)
    role_changed = pyqtSignal(str)
    new_role = pyqtSignal(str, str)
    toggle_sessions = pyqtSignal(bool)
    toggle_chat_alone = pyqtSignal(bool)
    toggle_context = pyqtSignal(bool)
    toggle_config = pyqtSignal(bool)
    theme_changed = pyqtSignal(str)

    def __init__(self, parent=None, theme_manager=None, llm_manager=None, role_config_manager=None, thread_manager=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.llm_manager = llm_manager
        self.role_config_manager = role_config_manager
        self.thread_manager = thread_manager
        self.setObjectName("main_toolbar")
        self.setContentsMargins(0, 0, 0, 4)
        # la barre d'outil ne peut plus être déplacée
        self.setMovable(False)
        # enlever le menu contextuel pour éviter de masque la toolbar.
        self.toggleViewAction().setVisible(False)

        # Bouton Settings avec menu deroulant
        self.setup_btn = QToolButton(self)
        self.setup_btn.setObjectName("toolbar_setup_btn")
        self.setup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setup_btn.setText("Settings")
        self.setup_btn.setToolTip("Your options")
        self.setup_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # Menu du bouton Settings
        settings_menu = QMenu(self)
        settings_menu.setObjectName("setupMenu")
        settings_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        settings_menu.setWindowFlags(settings_menu.windowFlags() | Qt.WindowType.FramelessWindowHint)
        settings_menu.setToolTipsVisible(True)

        # récupérer le theme actif
        self.current_theme = get_current_theme() or "select one"

        # Menu des thèmes
        self.theme_menu = QMenu(f"Theme ({self.current_theme})")
        self.theme_menu.setToolTipsVisible(True)
        self.theme_menu.setObjectName("themesMenu")  # Pour le CSS
        self.theme_menu.setToolTip("Select your theme")
        settings_menu.addMenu(self.theme_menu)
        self.theme_actions = {}  # Pour conserver les références
        for theme in COLOR_PALETTES:
            palette = COLOR_PALETTES[theme]

            # widget personnalisé pour l'action
            widget = QLabel(theme)
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setMinimumHeight(33)  # Hauteur minim. pour le clic
            widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            widget.setAutoFillBackground(True)
            # Applique le style avec les couleurs de chaque thème
            widget.setStyleSheet(
                f"""
                font-size: 15px;
                font-weight: bold;
                color: {palette['Text2']};
                background-color: {palette['Base1']};
                border-right : 6px solid ;
                border-right-color : {palette['Danger']};
                border-left : 6px solid ;
                border-left-color : {palette['Text']};
                border-top : 6px solid ;
                border-top-color : {palette['Warning']};
                border-bottom : 6px solid ;
                border-bottom-color : {palette['Accent']};
                padding: 6px;
                border-radius: 6px;
                margin: 3px;
            """
            )

            # Créez une QWidgetAction et ajoutez-y le widget
            action = QWidgetAction(self.theme_menu)
            action.setDefaultWidget(widget)
            action.setCheckable(True)
            is_active = theme == self.current_theme
            action.setChecked(is_active)
            widget.setProperty("active", is_active)  # pour styliser en qss l'état actif du theme
            # Connectez le signal
            action.triggered.connect(lambda _, t=theme: self.select_theme(t))

            self.theme_menu.addAction(action)
            self.theme_actions[theme] = (action, widget)  # Stockez pour mise à jour

        # Separateur
        settings_menu.addSeparator()

        # Afficher la boite de dialogue -modifiable- de requête (avec historique/contexte/RAG)
        self.show_query_dialog = True
        self.action_show_query = QAction("Show Final Query Dialog before sending", self, checkable=True)
        self.action_show_query.setChecked(self.show_query_dialog)
        self.action_show_query.setToolTip(
            "Show/hide the final query dialog box before sending request to LLM.\n"
            "Useful to monitor what is being sent and to change it if you want."
        )
        self.action_show_query.toggled.connect(self.set_show_query_dialog)
        settings_menu.addAction(self.action_show_query)

        self.generate_title = True
        self.action_generate_title = QAction("Generate a session title automatically", self, checkable=True)
        self.action_generate_title.setChecked(self.generate_title)
        self.action_generate_title.setToolTip(
            "If your session has no title (e.g. 'session_5'), asks the LLM to generate a title summarizing"
            " the subject of the session."
        )
        self.action_generate_title.toggled.connect(self.set_generate_title)
        settings_menu.addAction(self.action_generate_title)

        settings_menu.addSeparator()

        # plage temporelle de disponibilité du LLM en mémoire - keep_alive timeout (en minutes, 0 = jamais déchargé)
        self.action_keep_alive = QAction("", self)
        self.action_keep_alive.setToolTip(
            "Time to keep LLM alive in memory before unloading it."
            "\nWritten in Minutes, possibly 0.5 for 30sec, or -1 for infinite loading"
        )
        self.action_keep_alive.triggered.connect(self.set_keep_alive_timeout)
        settings_menu.addAction(self.action_keep_alive)

        # intervale temporel de vérification du statut de disponibilité du LLM (ms)
        self.llm_status_timer = 3000
        self.action_poll_interval = QAction("", self)
        self.action_poll_interval.triggered.connect(self.set_status_poll_interval)
        self.action_poll_interval.setToolTip(
            "Poll interval in ms between each request to monitor the LLM 'loaded' status"
            "\n...with the button : red = unloaded, green = loaded"
            "\nWritten in Milliseconds, possibly 2000 for 2sec"
        )
        settings_menu.addAction(self.action_poll_interval)

        # Rafraichir la table LLM properties en les synchronisant avec Ollama
        self.action_sync_models = QAction("Add Model/Refresh Model Properties", self)
        self.action_sync_models.setToolTip(
            "Synchronizes the LLM properties table\n" "Will insert missing models and, if you choose, let you review changes."
        )
        settings_menu.addAction(self.action_sync_models)
        self.action_sync_models.triggered.connect(self._on_refresh_clicked)

        settings_menu.addSeparator()

        # Rafraichir l'UI avec le QSS themes.qss
        action_refresh_qss = QAction("Refresh UI QSS", self)
        action_refresh_qss.triggered.connect(self.apply_qss)
        action_refresh_qss.setToolTip(
            "Refreshes interface stylesheet on-the-go.\nOnly useful when tweaking/editing themes.qss file"
        )
        settings_menu.addAction(action_refresh_qss)

        self.setup_btn.setMenu(settings_menu)
        self.addWidget(self.setup_btn)

        spacer1 = QWidget(self)
        spacer1.setObjectName("spacer1_wdg")
        spacer1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer1)

        # Bouton session pour visibilité
        self.btn_toggle_sessions = QPushButton(" Sessions ↩ ", self)
        self.btn_toggle_sessions.setObjectName("toolbar_btn_sessions")
        self.btn_toggle_sessions.setToolTip("Hides/shows the session panel")
        self.btn_toggle_sessions.setCheckable(True)
        self.btn_toggle_sessions.setChecked(True)
        self.addWidget(self.btn_toggle_sessions)

        # Bouton Chat ONLY pour visibilité
        self.btn_toggle_chat_alone = QPushButton("  📃  ", self)
        self.btn_toggle_chat_alone.setObjectName("toolbar_btn_chat_alone")
        self.btn_toggle_chat_alone.setToolTip("Shows only the chat panel")
        self.btn_toggle_chat_alone.setCheckable(True)
        self.btn_toggle_chat_alone.setChecked(True)
        self.addWidget(self.btn_toggle_chat_alone)

        # Bouton context -visibilité
        self.btn_toggle_context = QPushButton(self)
        self.btn_toggle_context.setText(" ↪ Context ")
        self.btn_toggle_context.setObjectName("toolbar_btn_context")
        self.btn_toggle_context.setToolTip("Hides/shows the context panel")
        self.btn_toggle_context.setCheckable(True)
        self.btn_toggle_context.setChecked(True)
        self.addWidget(self.btn_toggle_context)

        # Bouton config -visibilité
        self.btn_toggle_config = QPushButton(" ↪ Config ", self)
        self.btn_toggle_config.setObjectName("toolbar_btn_config")
        self.btn_toggle_config.setToolTip("Hides/shows the config panel")
        self.btn_toggle_config.setCheckable(True)
        self.btn_toggle_config.setChecked(True)
        self.addWidget(self.btn_toggle_config)

        spacer2 = QWidget(self)
        spacer2.setObjectName("spacer1_wdg")
        spacer2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer2)

        # prompt type button/menus
        prompt_tooltip = (
            "Type of Role (system prompt and inference parameters) config for your LLM .\n"
            "Default Load : On first start the system loads the default role and parameters for your LLM.\n"
            "Customization : Adjust the role or change the hyper-parameters to suit your needs. "
            "The defaults will change according to the LLM you choose.\n"
            "Save Configuration : Click Save Config to persist the current setting. "
            "The selected role and LLM, together with the system prompt and any modified parameters, will be stored.\n"
            "Add or Edit : Create a new custom role with + New Role or "
            "edit the JSON file directly at core\\role_config_defaults.json (and relaunch app in this case)."
        )
        self.prompt_label = QLabel("Role :")
        self.prompt_label.setObjectName("toolbar_prompt_label")
        self.prompt_label.setToolTip(prompt_tooltip)

        self.role_button = QPushButton(self)
        self.role_button.setObjectName("toolbar_role_button")
        self.role_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.role_button.setToolTip(prompt_tooltip)
        self.role_button.setMinimumWidth(140)
        self.role_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.role_button.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.role_menu = QMenu(self)
        self.role_menu.setObjectName("roleMenu")  # for QSS
        self.role_menu.setMinimumWidth(140)
        self.role_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.role_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.role_menu.setToolTipsVisible(True)
        self.role_button.setMenu(self.role_menu)
        # self.role_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # aides internes
        self._prompt_flat_actions = []  # type: list[QAction]
        self._prompt_current_text = ""  # last selected prompt text
        self._current_prompt_index = -1

        # Exposer les trois méthodes utilisées ailleurs
        self.role_button.findText = self._prompt_find_text
        self.role_button.setCurrentIndex = self._prompt_set_index
        self.role_button.currentText = self._prompt_current_text_func

        # construire le menu hiérarchique
        self.new_role_in_combo = "+ New Role"
        self._build_role_menu()

        self.addWidget(self.prompt_label)
        self.addWidget(self.role_button)

        # Load Prompt button
        self.btn_load_llm = QPushButton("Load LLM", self)
        self.btn_load_llm.setObjectName("toolbar_btn_load")
        self.btn_load_llm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load_llm.setToolTip("Loads selected LLM with the selected prompt/config (before sending request)")
        self.addWidget(self.btn_load_llm)

        # Indicateur d'état LLM (LED rouge/vert)
        self.llm_status_indicator = QLabel()
        self.llm_status_indicator.setObjectName("llm_status_indicator")
        self.llm_status_indicator.setFixedSize(20, 20)
        self.llm_status_indicator.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # self.llm_status_indicator.setStyleSheet("background:transparent; border:none;")
        self.llm_status_indicator.setToolTip(
            "indicates whether an LLM is loaded or not\nPoll interval timer can be defined in Settings"
        )
        self.set_llm_status(False)  # Par défaut rouge
        self.addWidget(self.llm_status_indicator)

        # Dropdown pour LLM selection
        llm_tooltip = (
            "Choose an LLM from the list below (which are those installed in Ollama).\n"
            "Hover over a model to view details such as size and family.\n"
            "Before sending a request, pick a role and verify or edit the System Prompt/parameters as needed.\n"
            "Click 'Load LLM' to activate the selection."
        )
        self.llm_label = QLabel("LLM :")
        self.llm_label.setObjectName("toolbar_llm_label")
        self.llm_label.setToolTip(llm_tooltip)
        self.addWidget(self.llm_label)

        # Dans ta méthode d'initialisation :
        llm_container = QWidget()
        llm_container.setObjectName("combo_button_container")
        llm_layout = QHBoxLayout(llm_container)
        llm_layout.setContentsMargins(0, 0, 0, 0)
        llm_layout.setSpacing(0)

        self.llm_combo = QComboBox(self)
        self.llm_combo.setObjectName("toolbar_llm_combo")
        self.llm_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.llm_combo.setFrame(False)
        self.llm_combo.setToolTip(llm_tooltip)
        self.llm_combo.setMinimumContentsLength(13)
        self.llm_combo.setMaxVisibleItems(20)

        # Editer les paramètres par défaut du LLM
        self.btn_edit_llm_params = QPushButton("🛠️", self)
        self.btn_edit_llm_params.setObjectName("btn_edit_llm_params")
        self.btn_edit_llm_params.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit_llm_params.setToolTip("Edit default parameters for the selected LLM")

        llm_layout.addWidget(self.llm_combo)
        llm_layout.addWidget(self.btn_edit_llm_params)
        self.addWidget(llm_container)

        # Connecter signals
        settings_menu.aboutToShow.connect(self._refresh_settings_actions)
        self.btn_load_llm.clicked.connect(self.toggle_llm.emit)
        self.llm_combo.currentTextChanged.connect(self.llm_changed)
        self.btn_edit_llm_params.clicked.connect(self._on_edit_llm_deflt_params_clicked)
        self.btn_toggle_sessions.toggled.connect(self.toggle_sessions)
        self.btn_toggle_chat_alone.toggled.connect(self.toggle_chat_alone)
        self.btn_toggle_context.toggled.connect(self.toggle_context)
        self.btn_toggle_config.toggled.connect(self.toggle_config)

    def _prompt_find_text(self, txt: str) -> int:
        """Return index of txt in the flat list of actions, -1 if not found."""
        for i, act in enumerate(self._prompt_flat_actions):
            if act.text() == txt:
                return i
        return -1

    def _prompt_set_index(self, idx: int) -> None:
        """Select the action at idx (emits role_changed)."""
        if 0 <= idx < len(self._prompt_flat_actions):
            self._prompt_flat_actions[idx].trigger()

    def _prompt_current_text_func(self) -> str:
        """Return the text of the last selected prompt."""
        return self._prompt_current_text

    def set_language(self, lang: str):
        """Changes language et rebuild Roles menu."""
        self.current_language = lang
        self.role_config_manager.set_current_language(lang)
        self._build_role_menu()

    def _build_role_menu(self) -> None:
        """Create a hierarchical QMenu for Role configs, + "New Role", + Roles language switch"""
        self.role_menu.clear()
        self._prompt_flat_actions.clear()
        hierarchy = self.role_config_manager.get_hierarchy()

        def _html(txt: str) -> str:
            escaped = txt.replace("\n", "<br>")
            return f"<html><body><p style='white-space:pre-wrap;'>{escaped}</p></body></html>"

        # Traiter chaque catégorie
        for category, data in hierarchy.items():
            base = data["base"]  # (name, descr) or (None, None)
            children = data["children"]  # list of (name, descr)

            # CAS 1: Base prompt existe, avec ou sans children
            if base[0] is not None:
                name, descr = base

                if children:
                    # Créer submenu pour cette catégorie
                    submenu = QMenu(category, self.role_menu)
                    submenu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                    submenu.setObjectName("submenu_children")
                    submenu.setToolTipsVisible(True)

                    # Ajouter base prompt au submenu
                    base_action = QAction(name, submenu)
                    base_action.setToolTip(_html(descr))
                    base_action.triggered.connect(functools.partial(self._role_action_triggered, name))
                    submenu.addAction(base_action)
                    self._prompt_flat_actions.append(base_action)

                    # Ajouter children au submenu
                    for child_name, child_descr in children:
                        child_action = QAction(child_name, submenu)
                        child_action.setToolTip(_html(child_descr))
                        child_action.triggered.connect(functools.partial(self._role_action_triggered, child_name))
                        submenu.addAction(child_action)
                        self._prompt_flat_actions.append(child_action)

                    # Ajouter submenu au main menu
                    submenu_action = QAction(category, self.role_menu)
                    submenu_action.setMenu(submenu)
                    self.role_menu.addAction(submenu_action)
                else:
                    # Base prompt sans children - ajouter directement à main menu
                    base_action = QAction(name, self.role_menu)
                    base_action.setToolTip(_html(descr))
                    base_action.triggered.connect(functools.partial(self._role_action_triggered, name))
                    self.role_menu.addAction(base_action)
                    self._prompt_flat_actions.append(base_action)

            # CAS 2: Pas base prompt, que des children
            elif children:
                # Créer submenu pour children
                submenu = QMenu(category, self.role_menu)
                submenu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                submenu.setObjectName("submenu_children")
                submenu.setToolTipsVisible(True)

                # Ajouter children au submenu
                for child_name, child_descr in children:
                    child_action = QAction(child_name, submenu)
                    child_action.setToolTip(_html(child_descr))
                    child_action.triggered.connect(functools.partial(self._role_action_triggered, child_name))
                    submenu.addAction(child_action)
                    self._prompt_flat_actions.append(child_action)

                # Ajouter submenu au main menu
                submenu_action = QAction(category, self.role_menu)
                submenu_action.setMenu(submenu)
                self.role_menu.addAction(submenu_action)

        # Ajouter le séparateur et l'action "New Role"
        self.role_menu.addSeparator()
        new_role_action = QAction("+ New Role", self.role_menu)
        new_role_action.setToolTip("Create a new role/system prompt/parameters default configuration")
        new_role_action.triggered.connect(self._ask_for_new_role)
        self.role_menu.addAction(new_role_action)

        # Ajout menu de sélection de langue
        self.role_menu.addSeparator()
        # détecter les langues disponibles
        langs = self.role_config_manager.available_languages()
        if not hasattr(self, "current_language"):
            # première initialisation : anglais par défaut
            self.current_language = self.role_config_manager.get_current_language()

        # créer le sous-menu parent
        submenu_language = QMenu(f"Language: {self.current_language.upper()}", self.role_menu)
        submenu_language.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        submenu_language.setObjectName("submenu_children")
        submenu_language.setToolTipsVisible(True)

        # ajouter une action par langue
        for lang_code in sorted(langs.keys()):
            lang_action = QAction(lang_code.upper(), submenu_language)
            lang_action.setCheckable(True)
            lang_action.setChecked(lang_code == self.current_language)

            def _switch_language(checked, code=lang_code):
                if not checked or code == self.current_language:
                    return
                saved_index = self._current_prompt_index if hasattr(self, "_current_prompt_index") else -1
                # recharger le RoleConfigManager avec la nouvelle langue
                self.role_config_manager.load_language(code)
                self.current_language = code
                # reconstruire le menu
                self._build_role_menu()
                if 0 <= saved_index < len(self._prompt_flat_actions):
                    restore_index = saved_index
                else:
                    restore_index = 0  # par défaut à la première entrée en cas de prblème
                self._prompt_set_index(restore_index)

            lang_action.triggered.connect(_switch_language)
            submenu_language.addAction(lang_action)

        # action parent qui ouvre le sous-menu
        submenu_language_action = QAction(submenu_language.title(), self.role_menu)
        submenu_language_action.setMenu(submenu_language)
        self.role_menu.addAction(submenu_language_action)

        # les tooltip sont visibles
        self.role_menu.setToolTipsVisible(True)

    def _role_action_triggered(self, name: str) -> None:
        """Called when a prompt/action is selected."""
        self._prompt_current_text = name
        self._current_prompt_index = self._prompt_find_text(name)
        self.role_button.setText(f"  {name}")
        self.role_changed.emit(name)

    def _ask_for_new_role(self) -> None:
        """Dialog to create a new prompt, then emit new_role."""
        name, ok = QInputDialog.getText(self, "Create a new prompt role", "Prompt role's name :")
        if not ok or not name.strip():
            return
        sys_prompt, ok = QInputDialog.getMultiLineText(
            self,
            "Define the default system prompt for the new prompt role",
            f"{name}'s default system prompt :",
        )
        if ok and sys_prompt.strip():
            self.new_role.emit(name.strip(), sys_prompt.strip())

    def _refresh_settings_actions(self):
        # 1) LLM Keep-Alive
        ka = self.llm_manager.keep_alive
        if ka is None or ka < 0:
            text_ka = "LLM Keep-Alive Timeout (Mn) : inf."
        else:
            text_ka = f"LLM Keep-Alive Timeout (Mn) : {ka/60:.2f}"
        self.action_keep_alive.setText(text_ka)

        # 2) LLM status timer (Poll Interval)
        # On relit la valeur courante dans l'UI (ou depuis le JSON)
        timer = getattr(self, "llm_status_timer", None)
        if timer is None and GUI_CONFIG_PATH.exists():
            data = json.loads(GUI_CONFIG_PATH.read_text())
            timer = data.get("llm_status_timer", 2000)
        text_pi = f"LLM Status Poll Interval (ms) : {timer}"
        self.action_poll_interval.setText(text_pi)

        self.action_show_query.setChecked(self.show_query_dialog)

        self.action_generate_title.setChecked(self.generate_title)

    def set_show_query_dialog(self, checked: bool):
        """Enable or disable showing the final query dialog.
        Called when the user toggles ``action_show_query``.
        Updates the flag, the action state and persists the change."""
        self.show_query_dialog = checked
        self.action_show_query.blockSignals(True)
        self.action_show_query.setChecked(checked)
        self.action_show_query.blockSignals(False)

        # Notify the main window that something changed.
        if hasattr(self.parent(), "save_gui_config"):
            self.parent().save_gui_config()

    def set_generate_title(self, checked: bool):
        """Setter to enable or disable generating a title for the session with requested LLM
        Called when the user toggles ``action_generate_title``
        Updates the flag, the action state and persists the change."""
        self.generate_title = checked
        self.action_generate_title.blockSignals(True)
        self.action_generate_title.setChecked(checked)
        self.action_generate_title.blockSignals(False)

        if hasattr(self.parent(), "save_gui_config"):
            self.parent().save_gui_config()

    def set_keep_alive_timeout(self):
        """sets the time during which the LLM stays loaded"""
        if not self.llm_manager:
            return
        # Demande un durée en minutes (-1 = ne jamais décharger)
        current = self.llm_manager.keep_alive / 60.0 if self.llm_manager.keep_alive >= 0 else -1.0
        value, ok = QInputDialog.getDouble(
            self,
            "LLM Keep-Alive Timeout",
            "Minutes (-1 = never unload, e.g. 0.5 = 30s):",
            current,
            -1.0,
            4000.0,
            2,
        )
        if ok:
            self.llm_manager.keep_alive = -1 if value < 0 else value * 60

    def set_status_poll_interval(self):
        """sets the time interval between each request to monitor if LLM is loaded or not"""
        # Demande un intervalle en ms
        value, ok = QInputDialog.getInt(
            self,
            "LLM Status (loaded/unloaded) Poll Interval",
            "Interval in ms:",
            getattr(self, "llm_status_timer", 2000),
            1000,
            60000,
            100,
        )
        if ok:
            self.llm_status_timer = value

    def set_llm_status(self, loaded: bool):
        """Switch for LLM 'loaded status' monitoring between green/red button"""
        # Solution 1: Recréer complètement le QLabel
        pixmap = create_status_indicator(loaded)
        self.llm_status_indicator.setPixmap(pixmap)

        self.btn_load_llm.setText("Unload LLM" if loaded else "Load LLM")

    def select_theme(self, theme_name):
        if not hasattr(self, "theme_manager"):
            raise RuntimeError("ThemeManager has not been initialized")
        if theme_name is None:
            theme_name = "Anthracite Carrot"
        try:
            self.theme_manager.apply_theme(theme_name)
            # self.themes_btn.setText(theme_name)
            self.current_theme = theme_name

            # Met à jour le titre du sous-menu pour afficher le thème courant
            # (action qui représente le sous-menu)
            submenu_action = self.theme_menu.menuAction()
            submenu_action.setText(f"Theme ({theme_name})")
            # et/ou
            self.theme_menu.setTitle(f"Theme ({theme_name})")

            # Injecte la bordure uniquement sur le QLabel actif
            for t, (action, widget) in self.theme_actions.items():
                is_active = t == theme_name
                action.setChecked(is_active)

                # Conserve le style de base
                # if widget.property("baseStyle") is None:
                #     widget.setProperty("baseStyle", widget.styleSheet())

                # base = widget.property("baseStyle")
                # # Ajoute ou retire la bordure selon l'état
                # if is_active:
                #     widget.setStyleSheet(base + "border:3px solid #61afef; border-radius:6px;")
                # else:
                #     widget.setStyleSheet(base)

            # Sauvegarder la configuration
            self.parent().save_gui_config()
            print(f"Theme '{theme_name}' successfully applied.")

            # EMIT SIGNAL Qt pour les autres modules
            self.theme_changed.emit(theme_name)

        except ValueError as e:
            QMessageBox.warning(self, "Error", str(e))
            print(f"Theme application error: {str(e)}")

    def _on_edit_llm_deflt_params_clicked(self):
        """User asked for edition of current selected LLM default parameters"""
        model_name = self.llm_combo.currentText()
        diff = self.llm_manager.props_mgr.edit_model_parameters(model_name)
        print(diff)
        updated_fields = []  # pour affichage des modèles updatés
        dlg = ModelDiffDialog(diff, edit_mode=True, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            fields_new_values = dlg.get_edited_fields()  # dict typé
            for k in fields_new_values.keys():
                updated_fields.append(k)
            if fields_new_values:
                self.llm_manager.props_mgr.update_properties(model_name=model_name, field_value_dict=fields_new_values)
        else:
            return  # annulation utilisateur
        if updated_fields:
            updates_txt = "\n".join(updated_fields)
            QMessageBox.information(
                self,
                "Model parameters edition finished",
                f"LLM Properties for {model_name} have been updated :\n\n{updates_txt}",
            )
        else:
            QMessageBox.information(
                self,
                "Refresh finished",
                f"No LLM Properties for {model_name} to update.",
            )

    def _on_refresh_clicked(self):
        """User asked for a manual refresh."""
        # Demander si l'utilisateur veut un "full diff" ou juste “add missing model”
        reply = QMessageBox.question(
            self,
            "Refresh mode",
            "Do you want to review/select changes for existing models?\n"
            "(Choosing 'No' will only add any newly-installed models.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        force_refresh = reply == QMessageBox.StandardButton.Yes

        # worker dans un qthread
        self.worker = ModelSyncWorker(
            props_mgr=self.llm_manager.props_mgr,
            force_refresh=force_refresh,
        )
        self.worker.progress.connect(self._show_progress)
        self.worker.finished.connect(self._on_sync_finished)
        self.thread_manager.start_qthread(self.worker)

    def _show_progress(self, txt: str):
        """Create a single spinner (or update its text) in the status bar."""
        status_bar = self.parent().statusBar()
        if hasattr(self, "_spinner") and self._spinner:
            self._spinner.setMessage(txt)
        else:
            self._spinner = create_spinner(text=txt)
            status_bar.addPermanentWidget(self._spinner)

    def _kill_spinner(self):
        """Stop the spinner and remove it from the status bar."""
        if hasattr(self, "_spinner") and self._spinner:
            try:
                self._spinner.stop_spinner()
            except Exception:
                pass
            finally:
                self._spinner = None

    def _on_sync_finished(self, diffs: list[dict]):
        """
        Called when ModelSyncWorker finishes.
        *diffs* is a list produced by LLMPropertiesManager.sync_missing_and_refresh().
        Each entry looks like:
            {
                "model":   <str>,
                "new_data":<flat dict from Ollama>,
                "diff":    {"field": (old, new), …}
            }
        """
        if not diffs or diffs == []:
            if hasattr(self, "_spinner") and self._spinner:
                self._kill_spinner()
            self.parent().statusBar().hide()
            QMessageBox.information(self, "Refresh finished", "No changes detected.")
            return
        else:
            if hasattr(self, "_spinner") and self._spinner:
                self._kill_spinner()
            self.parent().statusBar().hide()

        updated_models = []  # pour affichage des modèles updatés
        dlg = ModelDiffDialog(diffs, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            fields_to_update_per_model = dlg.selected_fields()
            if fields_to_update_per_model:
                for model, field_value_dict in fields_to_update_per_model.items():
                    #  demander à écrire les colonnes sélectionnées
                    self._apply_updates(
                        model_name=model,
                        field_value_dict=field_value_dict,
                    )
                    # un rapport pour chaque modèle updaté
                    # self._show_progress(f"Updated {entry['model']}")
                    updated_model = f"{model} : {[(field, value) for field, value in field_value_dict.items()]}"
                    updated_models.append(updated_model)

        # message final (rapport)
        if updated_models:
            updates_txt = "\n".join(updated_models)
            QMessageBox.information(
                self,
                "Refresh finished",
                f"LLM Properties have been updated :\n\n{updates_txt}",
            )
        else:
            QMessageBox.information(
                self,
                "Refresh finished",
                "No LLM Properties changes to update.",
            )

    def _apply_updates(self, model_name: str, field_value_dict: dict[str, str]) -> None:
        """
        Forward the update request to the core manager.
        """
        self.llm_manager.props_mgr.update_properties(
            model_name=model_name,
            field_value_dict=field_value_dict,
        )

    def apply_qss(self):
        """Apply a QSS file to the application on the fly without restarting."""
        set_current_theme(get_current_theme())

        # Recharger le fichier de palettes de couleurs
        self.theme_manager.reload_color_palettes()

        from core.theme.theme_manager import CURRENT_THEME

        # Réappliquer le thème courant
        self.theme_manager.apply_theme(CURRENT_THEME)

        # Sauvegarder la config utilisateur
        self.parent().save_gui_config()
        print("Theme (palettes and QSS) successfully refreshed.")

    def load_llms(self, models: list[dict]) -> None:
        """
        Populate the LLM dropdown with the provided list of model names.
        Args:
            llm_list (list[str]): A list of strings naming installed LLMs.
        """
        self.llm_combo.clear()
        # print(llm_list)
        # self.llm_combo.addItems(llm_list)
        sorted_models = self.sort_llm_list(models)
        embeddings_models = (
            "nomic-embed-text",
            "bge-m3",
            "mxbai-embed-large",
            "all-minilm",
            "snowflake-arctic-embed",
            "bge-large",
            "paraphrase-multilingual",
            "granite-embedding",
            "embeddinggemma",
            "qwen3-embedding",
        )
        for model in sorted_models:
            # on sort les embeddings de de notre liste de LLM
            if model["name"].startswith(embeddings_models):
                continue
            llm_size = self.convert_bytes_to_gb(model["size"])
            llm_name = model["name"]
            tooltip_text = f"LLM: {llm_name}\n" f"Size: {llm_size}\n" f"Family: {model['details']['family']}"
            self.llm_combo.addItem(llm_name)
            index = self.llm_combo.count() - 1
            self.llm_combo.setItemData(index, tooltip_text, Qt.ItemDataRole.ToolTipRole)

    def convert_bytes_to_gb(self, bytes_value: float) -> str:
        """Converts bytes to gigabytes (GB) with two decimal places."""
        gb = bytes_value / (1024**3)
        return f"{gb:.2f} GB"

    def sort_llm_list(self, llm_list: list[dict]) -> list[dict]:
        """Sorts a list of LLM dictionaries alphabetically by the 'name' key,
        with models containing '/' characters at the end, sorted alphabetically
        by the string after the '/'."""

        def sort_key(llm):
            name = llm["name"].lower()
            if "/" in name:
                return (1, name.split("/")[-1])  # Triés après les autres, par la string après '/'
            else:
                return (0, name)  # Trier par name, avant les autres

        return sorted(llm_list, key=sort_key)
