# -*- coding: utf-8 -*-
"""
Module: gui.py --- Defines : MainWindow
Description: PyQt6-based GUI for interacting with various LLM/prompt system locally.
It also handles loading/saving of GUI state, LLM parameters
(window geometry, splitter sizes, theme) in 'gui_config.json'.
"""
import json
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QByteArray, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMainWindow, QMessageBox, QSplitter

from core.config_manager import ConfigManager
from core.context_parser import ContextParser
from core.llm_manager import LLMManager
from core.message_manager.msg_proc import MissingConfigError, UserMessageProcessor
from core.models import PromptConfig
from core.prompt_config_manager import PromptConfigManager
from core.prompt_manager import PromptManager
from core.session_manager import SessionManager
from core.theme.theme_manager import GUI_CONFIG_PATH, ThemeManager, get_current_theme
from gui.thread_manager import QThread, ThreadManager
from gui.widgets.prompt_validation_dialog import show_prompt_validation_dialog

from .chat_panel import ChatPanel
from .config_panel import ConfigPanel
from .context_parser_panel import ContextBuilderPanel
from .llm_worker import LLMWorker
from .session_panel import SessionPanel
from .toolbar import Toolbar


class MainWindow(QMainWindow):
    """Main Window responsible for orchestration, signals connection, global session management"""

    MIN_SPLITTER_SIZES = [180, 500, 210, 180]  # Taille minimale pour chaque splitter

    def __init__(
        self,
        config_manager: ConfigManager,
        theme_manager: ThemeManager,
        session_manager: SessionManager,
        llm_manager: LLMManager,
    ):
        super().__init__()
        self.setWindowTitle("AInterfAI")
        # Injection des managers
        self.config_manager = config_manager
        self.theme_manager = theme_manager
        self.session_manager = session_manager
        self.llm_manager = llm_manager
        self.thread_manager = ThreadManager()
        self.prompt_manager = PromptManager(self.session_manager.db, session_manager=self.session_manager)
        self.prompt_config_manager = PromptConfigManager()
        self.context_parser = ContextParser(config_path=Path("core/context_parser_config.json"))
        self.llm_worker = None

        # État courant de l'application
        self.llm_loaded = False
        self.current_llm = None
        self.current_llm_name = None
        self.current_session_id = None
        self.generated_context: str = ""
        self.load_keep_alive_from_json()

        # Construction de l'UI/des panels et splitters
        self.toolbar = Toolbar(
            self,
            theme_manager=self.theme_manager,
            llm_manager=self.llm_manager,
            prompt_config_manager=self.prompt_config_manager,
        )
        self.addToolBar(self.toolbar)

        self.panel_sessions = SessionPanel(self, session_manager=self.session_manager)
        if self.theme_manager.current_theme is None:
            # récupère le thème courant depuis config ou valeur par défaut
            self.theme_manager.current_theme = get_current_theme() or "Anthracite Carrot"
        self.panel_chat = ChatPanel(
            self,
            theme_manager=self.theme_manager,
            toolbar=self.toolbar,
            ctx_parser=self.context_parser,
            session_manager=self.session_manager,
            thread_manager=self.thread_manager,
        )
        self.panel_context = ContextBuilderPanel(self, parser=self.context_parser, thread_manager=self.thread_manager)
        self.panel_config = ConfigPanel(self, session_manager=self.session_manager)
        self.message_processor = UserMessageProcessor(
            prompt_manager=self.prompt_manager,
            context_parser=self.context_parser,
            session_manager=self.session_manager,
            rag_config=self.panel_context._rag_config,
        )

        # Splitter entre sessions et chat (gauche)
        self.left_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.left_splitter.setObjectName("main_left")
        self.left_splitter.addWidget(self.panel_sessions)
        self.left_splitter.addWidget(self.panel_chat)

        # Autres Splitters
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("main_splitters")
        self.splitter.addWidget(self.left_splitter)
        self.splitter.addWidget(self.panel_context)
        self.splitter.addWidget(self.panel_config)
        self.setCentralWidget(self.splitter)
        self.splitter.setContentsMargins(0, 0, 0, 0)
        # self.splitter.setHandleWidth(10)

        # Charger la liste des LLMs et la peupler dans la toolbar
        llms = self.llm_manager.list_models()
        self.toolbar.load_llms(llms)
        # Chargement JSON / GUI GUI config (geometry, splitter sizes, theme)
        self.load_gui_config()

        # vérification passive de l'état de chargement d'un LLM pour l'indicateur d'état (vert/rouge)
        self.ollama_status_timer = QTimer(self)
        self.ollama_status_timer.timeout.connect(self.check_ollama_model_status)
        self.ollama_status_timer.start(
            self.toolbar.llm_status_timer if self.toolbar.llm_status_timer else 2000
        )  # toutes les 2 sec par defaut

        # Connexions
        self._connect_signals()

    def _connect_signals(self):
        """Connects all signals between UI and business logic."""
        # Chat
        self.panel_chat.user_message.connect(self.handle_user_message)
        self.panel_chat.font_size_changed.connect(lambda _: self.save_gui_config)
        # Toolbar
        self.toolbar.toggle_llm.connect(self.on_toggle_llm)  # charge ou décharge LLM
        self.toolbar.llm_changed.connect(self.on_load_role_llm_config)
        self.toolbar.prompt_changed.connect(self.on_load_role_llm_config)
        self.toolbar.new_prompt.connect(self.on_new_prompt)
        # hide/show panels
        self.toolbar.toggle_sessions.connect(lambda visible: self._toggle_panel(self.panel_sessions, visible))
        self.toolbar.toggle_chat_alone.connect(lambda visible: self._toggle_chat_panel(visible))
        self.toolbar.toggle_context.connect(lambda visible: self._toggle_panel(self.panel_context, visible))
        self.toolbar.toggle_config.connect(lambda visible: self._toggle_panel(self.panel_config, visible))
        # Context parser
        self.panel_context.context_generated.connect(self.on_context_generated)
        self.panel_context.new_session_requested.connect(self.create_new_session)
        self.panel_context.rag_handler_requested.connect(self._on_rag_handler_requested)
        self.panel_context.attach_processor(self.message_processor)
        # Config panel
        self.panel_config.save_config.connect(self.on_save_role_llm_config)
        self.panel_config.load_config.connect(self.on_load_role_llm_config)
        # Sessions panel
        self.panel_sessions.session_selected.connect(self.on_session_selected)
        self.panel_sessions.new_session.connect(self.create_new_session)
        self.panel_sessions.session_renamed.connect(self.on_rename_session)
        self.panel_sessions.delete_session.connect(self.on_delete_session)
        self.panel_sessions.export_markdown_requested.connect(self._handle_export_markdown)
        self.panel_sessions.export_html_requested.connect(self._handle_export_html)
        self.panel_sessions.session_list.move_to_folder.connect(self.on_move_to_folder)
        self.panel_sessions.new_folder.connect(self.on_new_folder)
        self.panel_sessions.edit_folder.connect(self.on_rename_folder)
        self.panel_sessions.delete_folder.connect(self.on_delete_folder)
        self.panel_sessions.folder_renamed.connect(self.on_rename_folder)

    def _toggle_panel(self, panel, visible):
        panel.setVisible(visible)
        QTimer.singleShot(200, self.panel_chat._refresh_bubble_layout)

    def _toggle_chat_panel(self, visible):
        for other_panel in (self.panel_sessions, self.panel_context, self.panel_config):
            other_panel.setVisible(visible)
        for other_btn in (
            self.toolbar.btn_toggle_sessions,
            self.toolbar.btn_toggle_context,
            self.toolbar.btn_toggle_config,
        ):
            other_btn.setChecked(visible)
        QTimer.singleShot(200, self.panel_chat._refresh_bubble_layout)

    def _show_prompt_validation_dialog(self, prompt_text: str) -> Optional[str]:
        """Return the final text if validated by user, else returns none."""
        return show_prompt_validation_dialog(self, prompt_text)

    def _reset_chat_panel_state(self):
        """Prepares the chatpanel before starting a new stream."""
        self.panel_chat.llm_streaming_started = False
        self.panel_chat.auto_scroll_enabled = True
        self.panel_chat.llm_bubble_widget = None
        self.panel_chat._stream_buffer = ""

    def handle_user_message(self, user_text: str):
        """Called when the user presses ENTER.
        Interface GUI -> core processing + orchestration of LLM streaming.
        """
        # 00. print le message user dans la console
        print("Your request :\n", user_text)
        # 0. Vérif. config / LLM chargé (identique au code actuel)
        if self.current_session_id is None:
            self.create_new_session()
        if self.current_config_id is None:
            cfg = self.apply_role_llm_config(
                self.toolbar.llm_combo.currentText(),
                self.toolbar.prompt_button.currentText(),
            )
            if cfg is None:
                QMessageBox.warning(
                    self,
                    "Missing configuration",
                    "No prompt configuration is loaded. Choose an prompt before sending a message.",
                )
                QTimer.singleShot(0, lambda: self.panel_chat.input.setText(user_text))
                return
            self.current_config_id = cfg.id

        if not self.current_llm:
            resp = QMessageBox.question(
                self,
                "load 'currently displayed' Prompt & LLM ?",
                "( To avoid this message in the future, before sending your request :\n"
                "1. change your selected combo Prompt/LLM if needed\n--> 2. press 'Load LLM' )\n\n"
                f"Do you want to send your request to :\n\n    LLM         '{self.toolbar.llm_combo.currentText()}'\n"
                f"\n    Prompt    '{self.toolbar.prompt_button.currentText()}'  ?",
            )
            if resp == QMessageBox.StandardButton.Yes:
                self.on_load_llm_and_config()
            else:
                QTimer.singleShot(0, lambda: self.panel_chat.input.setText(user_text))
                return
            # garde le message dans l'input et prévient l'utilisateur
            # QTimer.singleShot(0, lambda: self.panel_chat.input.setText(user_text))
            # self.panel_chat.append_message("system", "No prompt/LLM loaded. Please select one.")
            # return

        # 1. Récupération des infos UI (mode, prompts, fichiers, ...)
        mode_id = self.panel_context.mode_group.checkedId()  # 0=OFF, 1=FULL, 2=RAG
        current_system_prompt = self.panel_config.system_prompt.toPlainText().strip()
        selected_files = self.panel_context.selected_files()
        session_id = self.current_session_id
        llm_name = self.toolbar.llm_combo.currentText()
        role_name = self.toolbar.prompt_button.currentText()
        config_id = self.current_config_id
        # print(
        #     "mode_id : ",
        #     mode_id,
        #     "\nprompt_system : ",
        #     current_system_prompt,
        #     "\nselected_files : ",
        #     selected_files,
        #     "\nsession_id : ",
        #     session_id,
        #     "llm_name : ",
        #     llm_name,
        #     "role_name : ",
        #     role_name,
        #     "config_id : ",
        #     config_id,
        # )
        # 2. Dispatcher vers core.UserMessageProcessor
        try:
            if mode_id == 0:  # OFF
                proc_result = self.message_processor.process_off(
                    session_id=session_id,
                    user_text=user_text,
                    config_id=config_id,
                    current_system_prompt=current_system_prompt,
                    llm_name=llm_name,
                )
            elif mode_id == 1:  # FULL
                proc_result = self.message_processor.process_full(
                    session_id=session_id,
                    user_text=user_text,
                    selected_files=selected_files,
                    config_id=config_id,
                    current_system_prompt=current_system_prompt,
                    llm_name=llm_name,
                )
            else:  # RAG
                if not selected_files:
                    QMessageBox.information(self, "Info", "No file selected for RAG.")
                    QTimer.singleShot(0, lambda: self.panel_chat.input.setText(user_text))
                    return

                proc_result = self.message_processor.process_rag(
                    session_id=session_id,
                    user_text=user_text,
                    selected_files=selected_files,
                    config_id=config_id,
                    current_system_prompt=current_system_prompt,
                    llm_name=llm_name,
                )
        except MissingConfigError as e:
            QMessageBox.warning(self, "Missing configuration", str(e))
            QTimer.singleShot(0, lambda: self.panel_chat.input.setText(user_text))
            return
        except RuntimeError as e:  # erreurs du RAGHandler, du parser, ...
            QMessageBox.critical(self, "Processing error", str(e))
            QTimer.singleShot(0, lambda: self.panel_chat.input.setText(user_text))
            return

        # 3. Affichage du prompt pour validation si option checkée
        final_prompt = proc_result.formatted_prompt
        if self.toolbar.action_show_query.isChecked():
            final_prompt = self._show_prompt_validation_dialog(final_prompt)
            if final_prompt is None:  # user a annulé
                QTimer.singleShot(0, lambda: self.panel_chat.input.setText(user_text))
                return

        # 4. UI : afficher le message utilisateur
        self.panel_chat.append_user_bubble(user_text)
        QTimer.singleShot(0, self.panel_chat._scroll_to_bottom)

        # 5. création message LLM vide dans la BDD pour avoir un ID - persistance du msg
        llm_msg = self.session_manager.add_message(
            session_id,
            "llm",
            "",
            llm_name=llm_name,
            prompt_type=role_name,
            config_id=config_id,
        )
        llm_message_id = int(llm_msg.id)

        # 6. Lancer le worker de streaming dans un QThread
        self._launch_llm_worker(
            prompt=final_prompt,
            llm=self.current_llm,
            session_id=session_id,
            message_id=llm_message_id,
        )

    def _launch_llm_worker(self, prompt: str, llm, session_id: int, message_id: int):
        """Helper who creates the Qthread + the Worker, connects the signals"""
        # 1. créer le thread Qt
        worker_thread = QThread()
        worker_thread.setObjectName(f"LLMWorkerThread-{message_id}")

        # 2. créer le worker (QObject)
        worker = LLMWorker(
            llm=llm,
            session_id=session_id,
            session_manager=self.session_manager,  # for read-only
            message_id=message_id,
            generate_title=self.toolbar.generate_title,
        )
        worker.moveToThread(worker_thread)

        # 3. connecter les signaux du worker
        worker.start_streaming.connect(self.panel_chat.start_streaming_llm_bubble)
        worker.chunk_received.connect(self.panel_chat.update_streaming_llm_bubble)
        worker.llm_response_complete.connect(self._on_llm_response_complete)
        worker.session_title_generated.connect(self.on_rename_session)
        worker.error.connect(self._on_llm_error)

        # connexions DB
        # Ces slots vivent dans le thread GUI (MainWindow) -> ils sont exécutés immédiatement
        worker.message_update_requested.connect(self._persist_message_update)
        worker.title_update_requested.connect(self._persist_title_update)

        # bouton stop -> worker.stop()
        self.panel_chat.stop_requested.connect(worker.stop)

        # 4. gérer la fin du thread
        worker_thread.finished.connect(worker.deleteLater)
        worker_thread.finished.connect(worker_thread.deleteLater)

        # 5. enregistrer le thread dans le manager (pour le shutdown)
        self.thread_manager.register_qthread(worker_thread)

        # 6. démarrer le thread
        worker_thread.start()

        # 7. lancer le traitement (dans le thread)
        QTimer.singleShot(0, lambda: worker.start(prompt))

        # garder référence si besoin (ex: arrêt manuel) :
        self.llm_worker_thread = worker_thread
        self.llm_worker = worker

    def _persist_message_update(self, message_id: int, new_content: str):
        """Write the streamed answer into the DB. Executed in GUI thread."""
        self.session_manager.update_message(message_id=message_id, new_content=new_content)

    def _persist_title_update(self, session_id: int, new_title: str):
        """Write the generated title into the DB. Executed in GUI thread."""
        self.session_manager.rename_session(session_id=session_id, new_name=new_title)

    def _on_rag_handler_requested(self, session_id: int):
        # Ici, on délègue au processor, qui va gérer le RAGHandler
        self.message_processor.ensure_rag_handler(session_id)

    def _on_llm_response_complete(self, markdown: str):
        """
        Slot called when the LLM has finished streaming.
        -> saves the final version, refreshes the history, and goes back to zero.
        """
        # 1) Masquer le bouton Stop et réactiver l'input
        self.panel_chat.hide_stop_button()
        QTimer.singleShot(0, lambda: self.panel_chat.input.setEnabled(True))
        # arrêter le timer de rendu de streaming du panel chat
        self.panel_chat._batch_render_timer.stop()
        # 2) Lancer le rendu final HTML de ce qu'on a accumulé en streaming
        #    (met à jour la même bulle, en appelant le renderer worker)
        self.panel_chat._enqueue_render(
            self.panel_chat._stream_buffer,
            self.panel_chat._current_render_message_id,
        )

        # 3) Réinitialiser le flag de streaming dans ChatPanel
        self.panel_chat.llm_streaming_started = False
        self.panel_chat.llm_bubble_widget = None

        # recalculer les tailles des bubbles
        QTimer.singleShot(0, self.panel_chat._apply_deferred_bubble_adjustments)

        # 4) Recharger l'intégralité de la session depuis la BDD,
        #    pour afficher aussi le markdown historique et éviter toute incohérence
        QTimer.singleShot(0, lambda: self.on_session_selected(self.current_session_id))

    def _on_llm_error(self, message: str):
        self.panel_chat.append_message("system", message)
        QTimer.singleShot(0, lambda: self.panel_chat.input.setEnabled(True))

    def check_ollama_model_status(self):
        is_running = self.llm_manager.is_model_loaded(self.current_llm_name)

        if is_running != self.llm_loaded:
            self.llm_loaded = is_running
            self.toolbar.set_llm_status(is_running)
            # self.panel_chat.input.setEnabled(is_running)

    def on_toggle_llm(self):
        """Load or discharge the LLM as a function of the current state."""
        if self.llm_loaded:
            self.unload_llm()
        else:
            self.on_load_llm_and_config()

    def unload_llm(self):
        if self.current_llm_name:
            self.llm_manager.unload_ollama_model(self.current_llm_name)
            print(f"### --- Model '{self.current_llm_name}' Unloaded")

        self.current_llm = None
        self.toolbar.set_llm_status(False)
        # self.panel_chat.input.setEnabled(False)
        self.llm_loaded = False

    def on_load_llm_and_config(self):
        """Loads the selected prompt and its settings (in a thread so as not to block)."""
        if self.current_session_id is None:
            self.create_new_session()

        # Curseur "attente"
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

        llm_name = self.toolbar.llm_combo.currentText()
        params = self.panel_config.get_parameters()

        def _worker_load():
            try:
                # APPEL BLOQUANT déplacé hors du thread GUI
                llm = self.llm_manager.get_llm(llm_name, params.copy())
                # Stocke le résultat et programme la suite sur le thread Qt
                self._loaded_llm = llm
                self.current_llm_name = llm_name
                QTimer.singleShot(0, self._after_llm_loaded)
            except Exception as e:
                # Propage l'erreur sur le thread Qt
                err = str(e)
                QTimer.singleShot(0, lambda: self._on_llm_error(err))

        threading.Thread(target=_worker_load, daemon=True).start()

    def _after_llm_loaded(self):
        """Internal slot - on return on GUI thread."""
        # 1) Récupère le LLM chargé
        self.current_llm = self._loaded_llm
        llm_name = self.toolbar.llm_combo.currentText()
        self.current_llm_name = llm_name

        # 3) Reactiver l'input
        self.panel_chat.input.setEnabled(True)
        self.panel_chat.input.setFocus()
        # changer l'indicateur de chargement LLM en vert
        self.toolbar.set_llm_status(True)
        self.llm_loaded = True
        # 4) Curseur normal
        QApplication.restoreOverrideCursor()

    def on_new_prompt(self, role_name: str, role_system_prompt: str):
        """
        Slot called when choosing '+ New Role' in the combo.
        1) Asks the user a name and a default system prompt for the Prompt type
        2) Creates a new prompt_Config entry in prompt_config_defaults.json and in DB
        3) Reinjects this name in the combo just before '+ New Role'
        4) Automatically selects this new prompt and reloads the config panel
        """
        llm_name = self.toolbar.llm_combo.currentText()
        # 1) Créer en base via ConfigManager
        #    On reprend les defaults s'il y en a, sinon on part d'un dict vide.

        if role_name not in self.prompt_config_manager.get_types():
            prompt_dict = {
                "description": role_system_prompt,
                "temperature": 0.7,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "top_p": 0.95,
                "min_p": 0.05,
                "default_max_tokens": 8192,
            }
            self.prompt_config_manager.add_new_prompt(role_name, prompt_dict)
        defaults = self.prompt_config_manager.get_config(role_name)
        try:
            self.config_manager.save_role_config(llm_name, role_name, defaults)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Impossible to create the prompt : {e}")
            return

        # 2) Mettre à jour le menu prompt_button
        self.toolbar._build_prompt_menu()

        # 3) Sélectionner le nouvel prompt
        self.toolbar._prompt_action_triggered(role_name)

        # 4) recharger la config de cet prompt dans le panneau ConfigPanel
        self.on_load_role_llm_config()

    def refresh_sessions(self):
        """Refreshes the list of sessions in the session panel."""
        folders = self.session_manager.list_folders()
        sessions = self.session_manager.list_sessions()
        if (folders, sessions) == getattr(self, "_last_loaded_sessions", (None, None)):
            return  # pas de changement -> pas besoin de recharger
        self._last_loaded_sessions = (folders, sessions)
        try:
            self.panel_sessions.load_sessions(folders, sessions)
        except Exception as e:
            print(f"Error when loading sessions : {e}")

    def on_session_selected(self, session_id: int):
        """Displays all DB messages of the session in the ChatPanel."""
        # print("on_session_selected... start")
        # if getattr(self, "current_session_id", None) == session_id:
        #     return  # même session -> pas de boulot lourd
        self.current_session_id = session_id
        # forcer la relecture de la BDD
        self.session_manager.db.expire_all()
        # vide l'historique
        self.panel_chat.clear_history()
        # Récupère l'objet Session pour ses metadata
        sess = self.session_manager.get_session(session_id)
        if not sess:
            return
        # Récupère la config et le modèle du dernier message LLM
        last_llm = next((m for m in reversed(sess.messages) if m.sender == "llm"), None)
        self.current_config_id = last_llm.config_id if last_llm else None
        self.current_llm_name = last_llm.llm_name if last_llm else None
        # Cacher les boutons édition/suppression
        self.panel_chat._btn_edit.hide()
        self.panel_chat._btn_delete.hide()
        # Informer les panels
        self.panel_chat.set_session_id(session_id)
        self.panel_context.set_session_id(session_id)
        messages = sess.messages
        # pour chaque message, affiche user ou llm bubble
        for m in messages:
            self.panel_chat.append_message(m.sender, m.content, m.id)
        # recalculer/adapter les largeurs de bubbles après que tout soit affiché
        self.panel_chat.set_default_font_size(self.panel_chat._default_font_size)
        QTimer.singleShot(0, self._finalize_chat_layout)
        self.panel_chat.update_token_counter()
        # print("debug : on_session_selected... end")

    def _finalize_chat_layout(self):
        self.panel_chat._refresh_history_layout()
        QTimer.singleShot(0, self.panel_chat._force_scroll_to_bottom)

    def create_new_session(self):
        """Creates a new session in the database and refreshes the session list."""
        # on ne passe que folder_id=None, et on génère un nom vide pour l'instant
        session = self.session_manager.create_session(folder_id=None, session_name=None)
        print(f"new session created : session {session.id}")

        # 1) Recharge la liste de sessions
        self.refresh_sessions()
        # 2) Sélectionne dans panel_sessions.session_list le nouvel item
        sl = self.panel_sessions.session_list  # widget de liste de sessions
        for i in range(sl.count()):
            item = sl.item(i)  # QListWidgetItem
            if item.data(Qt.ItemDataRole.UserRole) == session.id:
                sl.setCurrentItem(item)
                item.setSelected(True)
                break
        # 3) Lance la même logique que si on avait cliqué dessus
        self.on_session_selected(session.id)

    def on_rename_session(self, session_id: int, new_name: str):
        """Opens a dialogue to rename the session."""
        # print(f"session_renamed emitted with session id {session_id} with text {new_name}")
        if new_name:
            self.session_manager.rename_session(session_id, new_name)
            # recharger la liste
            self.panel_sessions.load_sessions(self.session_manager.list_folders(), self.session_manager.list_sessions())
            print(f"session n°{session_id} renamed : {new_name}")
        else:
            return

    def on_delete_session(self, session_id: int):
        """Removes the session and updates the UI."""
        confirm = QMessageBox.question(
            self,
            "DELETE",
            "Do you confirm the deletion?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.session_manager.delete_session(session_id)
            self.panel_sessions.load_sessions(self.session_manager.list_folders(), self.session_manager.list_sessions())
            # si c'était la session courante, on vide le chat
            if self.current_session_id == session_id:
                self.panel_chat.clear_history()
                self.current_session_id = None

    def on_new_folder(self):
        """
        Slot called when sessionPanel emits new_folder.
        Opens a dialog box, creates the folder and refreshes.
        """
        # 1) Demander le nom du dossier
        name, ok = QInputDialog.getText(self, "New folder", "Folder Name :")
        if not ok or not name.strip():
            return  # annulation ou vide

        # 2) Création en base
        try:
            folder = self.session_manager.create_folder(name.strip())
            print(f"Folder created : id={folder.id}, name={folder.name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unable to create the folder : {e}")
            return

        # 3) Rafraîchir l'affichage
        self.refresh_sessions()

    def on_move_to_folder(self, session_id: int, folder_id: object, target_session_id: object):
        """
        session_id : The moved session
        folder_id  : the ID of the folder if we have droped on a folder
        target_session_id : the ID of a session if we have droped on a session
        """
        # 1) si on a déposé la session sur soi-même, on ne fait rien
        if session_id == target_session_id:
            return

        # 2) Cas dépôt sur un dossier existant
        if folder_id is not None:
            try:
                self.session_manager.move_session_to_folder(session_id, folder_id)
                print(f"➡️ Session {session_id} moved in folder {folder_id}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Unable to move : {e}")
            finally:
                self.refresh_sessions()
            return

        # 3) Cas dépôt sur une autre session -> on doit créer un nouveau dossier
        if target_session_id is not None:
            try:
                folder = self.session_manager.create_folder()
                print(f"Folder created {folder.id} «{folder.name}»")
                # 3b) déplacer LES DEUX sessions dedans
                for sid in (session_id, target_session_id):
                    self.session_manager.move_session_to_folder(sid, folder.id)
                    print(f"Session {sid} moved in new folder {folder.id}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Unable to create/move : {e}")
            finally:
                self.refresh_sessions()
            return

        # 4) Cas dépôt « à la racine » (ni sur session ni sur dossier) :
        try:
            # déclasse de tout dossier
            self.session_manager.move_session_to_folder(session_id, None)
            print(f"Session {session_id} moved to the root")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unable to move to the root : {e}")
        finally:
            self.refresh_sessions()

    def on_rename_folder(self, folder_id: int, new_name: str = None):
        if new_name is None:
            # si appelé via edit_folder (bouton), ouvrez QInputDialog
            new_name, ok = QInputDialog.getText(self, "Rename Folder", "New name :")
            if not ok or not new_name.strip():
                return
        self.session_manager.rename_folder(folder_id, new_name.strip())
        self.refresh_sessions()

    def on_delete_folder(self, folder_id: int):
        resp = QMessageBox.question(self, "Delete folder", "Do you confirm the suppression ?")
        if resp == QMessageBox.StandardButton.Yes:
            self.session_manager.delete_folder(folder_id)
            self.refresh_sessions()

    def on_context_generated(self, markdown: str, out_path: str):
        """
        Slot called when the ContextBuilderPanel generates the Markdown.
        It is stored to inject it then into the prompt system.
        """
        self.generated_context = markdown
        print(f"Context files converted to markdown ({len(markdown.split())} words) and saved in {out_path}")

    def _handle_export_markdown(self, session):
        mydocs_path = Path("mydocs")
        if not mydocs_path.exists() or not mydocs_path.is_dir():
            mydocs_path.mkdir()
        path = QFileDialog.getSaveFileName(
            self, "Export Session to Markdown", f"mydocs\\{session.session_name}.md", "Markdown Files (*.md)"
        )[0]
        if not path:
            return

        markdown_export = self.panel_chat._renderer_worker._renderer.session_to_markdown(session)
        print(markdown_export)
        with open(path, "w", encoding="utf-8") as f:
            # construction du Markdown
            f.write(markdown_export)
            print(f"{session.session_name}.md saved in {path}")

    def _handle_export_html(self, session):
        mydocs_path = Path("mydocs")
        if not mydocs_path.exists() or not mydocs_path.is_dir():
            mydocs_path.mkdir()
        path = QFileDialog.getSaveFileName(
            self, "Export Session to HTML", f"mydocs\\{session.session_name}.html", "HTML Files (*.html)"
        )[0]
        if not path:
            return
        html_export = self._session_to_html(session)
        with open(path, "w", encoding="utf-8") as f:
            # ici tu construis ton contenu HTML
            f.write(html_export)

    def _session_to_html(self, session):
        return self.panel_chat._renderer_worker._renderer.session_to_html(session)

    def on_save_role_llm_config(self):
        """Back up the prompt's current configuration in DB."""
        llm_name = self.toolbar.llm_combo.currentText()
        prompt = self.toolbar.prompt_button.currentText()
        params = self.panel_config.get_parameters()
        self.config_manager.save_role_config(llm_name, prompt, params)

    def on_load_role_llm_config(self):
        """get Load from the DB the prompt's config and updates the panel."""
        llm = self.toolbar.llm_combo.currentText()
        prompt = self.toolbar.prompt_button.currentText()
        if not prompt or not llm:
            return
        self.apply_role_llm_config(llm, prompt)

    def apply_role_llm_config(self, llm_name: str, role_name: str) -> Optional[PromptConfig]:
        """
        Loads or creates the config PromptConfig for (llm_name, role_name),
        updates the widgets of panel_config and returns the cfg object.
        """
        # 0)
        # 1) Charger ou créer la config
        cfg = self.config_manager.load_role_config(llm_name, role_name)

        if cfg is None:
            # Defaults depuis JSON
            prompt_defaults = self.prompt_config_manager.get_config(role_name)
            # Fusion avec les valeurs DB LLMProperties
            merged_defaults = self.llm_manager.props_mgr.merge_with_defaults(prompt_defaults, llm_name)

            cfg = self.config_manager.save_role_config(
                llm_name,
                role_name,
                merged_defaults,
            )

        if cfg is None:
            QMessageBox.critical(
                self,
                "Error",
                f'Impossible to load/create the config for the prompt "{role_name}" and the LLM "{llm_name}".',
            )
            return None

        # 2) Mémoriser l'ID pour build_prompt
        self.current_config_id = cfg.id

        # 3) Mettre à jour tous les widgets de panel_config
        self.panel_config.system_prompt.setPlainText(cfg.description or "")
        self.panel_config.temperature.setValue(int(cfg.temperature * 100))
        self.panel_config.top_k_slider.setValue(cfg.top_k)
        self.panel_config.repeat_penalty.setValue(int(cfg.repeat_penalty * 100))
        self.panel_config.top_p.setValue(int(cfg.top_p * 100))
        self.panel_config.min_p.setValue(int(cfg.min_p * 100))
        self.panel_config.max_tokens.setValue(cfg.default_max_tokens)
        self.panel_config.flash_attention.setChecked(cfg.flash_attention)
        self.panel_config.kv_cache.setCurrentText(cfg.kv_cache_type)
        self.panel_config.thinking.setChecked(bool(cfg.think))

        # 4) Remettre les defaults LLMProperties si besoin
        self.panel_config.set_model_defaults(llm_name)

        return cfg

    def load_keep_alive_from_json(self):
        """Charger la valeur de keep_alive depuis le fichier JSON et mettre à jour LLMManager"""
        if GUI_CONFIG_PATH.exists():
            data = json.loads(GUI_CONFIG_PATH.read_text())
            keep_alive_value = data.get("keep_alive")
            if keep_alive_value is not None:
                self.llm_manager.keep_alive = keep_alive_value

    def load_gui_config(self) -> None:
        """Load GUI configuration from JSON or initialize defaults."""
        if GUI_CONFIG_PATH.exists():
            data = json.loads(GUI_CONFIG_PATH.read_text())

            # Restaurer la géométrie des fenêtres
            geom_hex = data.get("geometry", "")
            if geom_hex:
                self.restoreGeometry(QByteArray.fromHex(geom_hex.encode()))

            # Restaurer les tailles de séparation
            sizes = data.get("splitter_sizes", [])
            if isinstance(sizes, list):
                self.splitter.setSizes(sizes)

            # Restaurer le thème/style
            theme = data.get("theme", "")
            if theme:
                self.theme_manager.apply_theme(theme)
            font_size = data.get("font_size", 16)
            if font_size:
                self.panel_chat.set_default_font_size(font_size)

            prompts_language = data.get("prompts_language", "en")
            if prompts_language is not None:
                self.toolbar.set_language(prompts_language)

            last_llm = data.get("last_llm")
            if last_llm:
                idx = self.toolbar.llm_combo.findText(last_llm)
                if idx != -1:
                    self.toolbar.llm_combo.setCurrentIndex(idx)

            last_prompt = data.get("last_prompt")
            if not last_prompt:
                self.toolbar.prompt_button.setCurrentIndex(0)
            if last_prompt:
                idx = self.toolbar.prompt_button.findText(last_prompt)
                if idx != -1:
                    self.toolbar.prompt_button.setCurrentIndex(idx)
                else:  # fallback si changement de langue et prompt de l'ancienne
                    self.toolbar.prompt_button.setCurrentIndex(0)

            last_context_cfg = data.get("last_context_cfg", "default")
            if last_context_cfg:
                self.panel_context.set_config_name(last_context_cfg)

            show_query_dialog = data.get("show_query_dialog")
            if show_query_dialog is not None:
                self.toolbar.show_query_dialog = show_query_dialog

            generate_title = data.get("generate_title")
            if generate_title is not None:
                self.toolbar.generate_title = generate_title

            keep_alive = data.get("keep_alive")
            if keep_alive is not None:
                self.llm_manager.keep_alive = keep_alive

            llm_status_timer = data.get("llm_status_timer")
            if llm_status_timer is not None:
                self.toolbar.llm_status_timer = llm_status_timer

        else:
            # 1ère Exécution: utiliser les valeurs par défaut actuelles et enregistrer
            font_size = 14
            self.theme_manager.apply_theme("Anthracite Carrot")
            self.splitter.setSizes([200, 600, 200, 200])
            self.save_gui_config()

    def save_gui_config(self) -> None:
        """Save current GUI configuration to JSON file."""
        geom = self.saveGeometry().toHex().data().decode()
        sizes = self.splitter.sizes()
        sizes = [max(size, self.MIN_SPLITTER_SIZES[i]) for i, size in enumerate(sizes)]
        theme_name = self.theme_manager.current_theme
        last_llm = self.toolbar.llm_combo.currentText()
        last_prompt = (
            self.toolbar.prompt_button.currentText()
            if self.toolbar.prompt_button.currentText() != self.toolbar.new_prompt_in_combo
            else "chat"
        )
        prompts_language = str(self.prompt_config_manager.get_current_language())

        data = {
            "geometry": geom,
            "splitter_sizes": sizes,
            "theme": theme_name,
            "last_llm": last_llm,
            "last_prompt": last_prompt,
            "font_size": self.panel_chat._default_font_size,
            "last_context_cfg": self.panel_context.parser.config_name,
            "show_query_dialog": self.toolbar.show_query_dialog,
            "generate_title": self.toolbar.generate_title,
            "keep_alive": self.llm_manager.keep_alive,
            "llm_status_timer": self.toolbar.llm_status_timer,
            "prompts_language": prompts_language,
        }
        GUI_CONFIG_PATH.write_text(json.dumps(data, indent=2))

    def resizeEvent(self, event):
        """Override resizeEvent to refresh ChatPanel with _refresh_bubble_layout()"""
        super().resizeEvent(event)
        if self.panel_chat:
            QTimer.singleShot(0, self.panel_chat._refresh_bubble_layout)

    def closeEvent(self, event) -> None:
        """Override closeEvent to persist GUI settings and unload currently loaded LLM before exit."""
        self.save_gui_config()
        self.unload_llm()
        self.thread_manager.shutdown()
        super().closeEvent(event)
