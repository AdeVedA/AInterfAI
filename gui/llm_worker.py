import asyncio
import re
import traceback

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class LLMWorker(QObject):
    """
    Worker to execute a LLM streaming call, in a non-blocking way in the QT interface.
    A new LLMWorker is instantiated with each user message.
    """

    start_streaming = pyqtSignal(int)  # signal avec l'id du message à streamer
    chunk_received = pyqtSignal(str)  # Signal émis pour chaque chunk de réponse reçu
    error = pyqtSignal(str)  # Signal émis en cas d'erreur
    llm_response_complete = pyqtSignal(str)  # Signal émis à la fin du streaming avec tout le texte
    session_title_generated = pyqtSignal(int, str)
    # signaux pour écritures BDD – gérées dans le GUI thread
    message_update_requested = pyqtSignal(int, str)  # (message_id, new_content)
    title_update_requested = pyqtSignal(int, str)  # (session_id, new_title)

    def __init__(
        self,
        llm,
        session_id: int,
        session_manager,
        message_id: int,
        generate_title: bool = True,
        image_base64: str = None,
    ):
        super().__init__()
        self.llm = llm
        self.session_id = session_id
        self.session_manager = session_manager
        self.message_id = message_id

        self._image_base64 = image_base64
        self._prompt = ""  # Stocke le message utilisateur
        self._stream_buffer = ""  # Contenu complet reçu du LLM
        self._stop_flag = False

        self._generate_title = generate_title

    def start(self, prompt: str):
        """
        Entry point called from the GUI (main thread)
        Starts the process in a separate thread.
        """
        self._prompt = prompt  # Sauvegarde du texte utilisateur pour l'utiliser dans le thread
        QTimer.singleShot(0, self._run_asyncio)
        # thread = threading.Thread(target=self._run_asyncio_thread, daemon=True)
        # self.thread_manager.register_thread(thread)
        # thread.start()

    def stop(self):
        """Requests the stopping/cancelation of the streaming."""
        self._stop_flag = True

    def _run_asyncio(self):
        """Execute the LLM async streaming coroutine independently inside the QThread."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._stream_llm())
        except Exception as e:
            self.error.emit(f"LLMWorker - Unexpected error in _run_event_loop : {e}")
        finally:
            # On ne ferme PAS la boucle ici pour éviter "Event loop is closed"
            pass

    async def _stream_llm(self):
        """
        Built the prompt and launches streaming from the LLM.
        Emits the chunks one after another, and saves the full result.
        """
        # print("LLMWorker: start")
        if self.message_id is not None:
            self.start_streaming.emit(self.message_id)
        # Lier l'image si nécessaire – this returns a *new* OllamaLLM
        #    that carries the images in its internal request payload.
        llm_to_use = self.llm
        if self._image_base64:
            # bind pour associer une copie de l'image à l'instance llm
            llm_to_use = self.llm.bind(images=[self._image_base64])
        try:
            # Streaming : récupération des chunks de texte un par un
            self._stream_buffer = ""
            async for chunk in llm_to_use.astream(self._prompt):
                if self._stop_flag:
                    print("⛔ Streaming interrupted by the user")
                    break
                self._stream_buffer += chunk
                self.chunk_received.emit(chunk)  # Envoi à l'interface Qt
            # print("LLMWorker: 'for chunk in' loop finished ")

            # À la fin du streaming : met à jour le record existant
            if self.session_id is not None and self._prompt is not None:
                # print(f"Database LLM message update (session_id={self.session_id}, id={self.message_id})")
                #
                self.message_update_requested.emit(self.message_id, self._stream_buffer.strip())
                # self.session_manager.update_message(
                #     message_id=self.message_id, new_content=self._stream_buffer.strip()
                # )
                print(
                    f"End of streaming, updated Database LLM message (session_id={self.session_id}, "
                    f"message_id={self.message_id})"
                )

            # print("LLMWorker: stop before emiting stream_buffer through llm_response_complete")
            # Envoi du signal final avec tout le contenu
            self.llm_response_complete.emit(self._stream_buffer.strip())
            # print("LLMWorker: stop after emiting stream_buffer through llm_response_complete")

            # génération d'un titre automatique
            if self.session_id and self._generate_title and not self._stop_flag:
                print("generating session title...")
                await self._maybe_generate_session_title()

        except Exception as e:
            traceback.print_exc()
            self.error.emit(f"LLMWorker - Error during streaming LLM : {e}")

    async def _maybe_generate_session_title(self):
        """
        If the name of the session is still by default (ex: 'session_27'),
        generates a title automatically for the session. runs via the LLM.
        """
        try:
            session = self.session_manager.get_session(self.session_id)
            if not session:
                return

            # Vérifie si le titre est du type "session_XX"
            if not re.fullmatch(r"session_\d+", session.session_name):
                return

            # print(f"LLMWorker : Automatic title generation for {session.session_name}")

            # Prompt court pour le résumé
            prompt = f"""You are a title generator.
Return ONLY a title of maximum 27 characters, without final punctuation, without quotes, without beacons,
without an explanation sentence, summarizing the theme of this conversation :
Question : {self._prompt}
Answer : {self._stream_buffer}
Expected title : """
            # print(prompt)
            # new_title = self.llm.invoke(prompt).strip()
            # exécuter dans une file d'attente de threads pour la réactivité du QThread
            loop = asyncio.get_running_loop()
            raw_title = await loop.run_in_executor(None, lambda: self.llm.invoke(prompt).strip())

            def clean_title(raw: str) -> str:
                # Supprime guillemets, balises, etc.
                title = raw.strip()
                title = re.sub(r"<[^>]+>", "", title)
                title = title.strip("\"'*")
                title = re.sub(r"\s+", " ", title)  # espaces multiples
                title = title.rstrip(".")
                return title[:31]

            # Nettoyage éventuel (enlève guillemets ou ponctuation finale)
            new_title = clean_title(raw_title)

            if new_title:
                # demander au thread du GUI de sauvegarder le nouveau titre
                self.title_update_requested.emit(self.session_id, new_title)
                self.session_title_generated.emit(self.session_id, new_title)
                print(f"New title generated : {new_title}")

        except Exception as e:
            traceback.print_exc()
            self.error.emit(f"LLMWorker - Automatic title generation error : {e}")
