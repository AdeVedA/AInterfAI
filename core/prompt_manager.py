"""
Module: prompt_manager.py
Description: Construction and execution of LLM prompt chains with history.
"""

from typing import Any, Callable, Dict, List, Tuple

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.base import Runnable
from langchain_core.runnables.history import RunnableWithMessageHistory
from sqlalchemy.orm import Session

from core.models import RoleConfig
from core.rag.config import RAGConfig


class SimpleChatHistory:
    """
    Wrapper minimal pour RunnableWithMessageHistory :
    stocke .messages (list) et expose add_messages().
    """

    def __init__(self, messages: list[dict]):
        self.messages = messages

    def add_messages(self, new_messages: list[dict]) -> None:
        self.messages.extend(new_messages)


class PromptManager:
    """
    Manages the assembly of prompts from base configurations
    and execution with history via Langchain.
    """

    def __init__(self, db_session: Session, system_prompt_text: str = None, session_manager=None):
        """
        Args:
            db_session (Session): Session SQLAlchemy pour accéder aux tables.
        """
        self.db = db_session
        self.system_prompt_text: str = system_prompt_text or ""
        self.session_mgr = session_manager

    def set_system_prompt(self, text: str):
        """
        Replaces the internal prompt system with "text".
        To call from Mainwindow.handle_user_Message before each LLM request.
        """
        self.system_prompt_text = text or ""

    def escape_braces(self, text: str, keep_placeholders: set[str] | None = None) -> str:
        """
        Double all braces except those that correspond to authorized placeholders.
        """
        if not text:
            return text

        # doubler toutes les accolades
        escaped = text.replace("{", "{{").replace("}", "}}")

        # remettre les placeholders permis à leur forme originale
        if keep_placeholders:
            for ph in keep_placeholders:
                escaped = escaped.replace(f"{{{{{ph}}}}}", f"{{{ph}}}")

        return escaped

    def build_prompt(
        self,
        config_id: int,
        model_name: str,
        current_system_prompt: str,
        user_inputs: Dict[str, str],
    ) -> Tuple[ChatPromptTemplate, Dict[str, Any]]:
        """
        Build a Langchain ChatPrompt and also returns
        LLM parameters (temperature, top_k, etc.).

        Args:
            config_id: identifier of RoleConfig in database.
            model_name: model name (ex: 'mistral:latest').
            user_inputs: mapping placeholder->value (ex: {'{user_input}': 'Hello, ca va ?'}).

        Returns:
            prompt_template (ChatPromptTemplate): prompt ready to be invoked.
            llm_params (dict): Parameteers to go to LLM.
        """
        # 0) Charger la configuration depuis BDD pour fallback
        cfg: RoleConfig = self.db.get(RoleConfig, config_id)
        # llm_props = self.db.get(LLMProperties, model_name)
        if cfg is None:
            raise ValueError(f"Aucune configuration RoleConfig trouvée pour config_id={config_id!r}")

        # 1) Préparer les messages de contexte initial (assembler la liste des messages)
        messages: list[dict] = []

        # 2a) Prompt système global, passé en argument du manager
        system_prompt = current_system_prompt or (cfg.description or "")
        if system_prompt:
            escaped_sys = self.escape_braces(system_prompt, keep_placeholders=set())
        # 2b) Fallback Prompt système spécifique à la config (description)
        else:
            escaped_sys = self.escape_braces(cfg.description, keep_placeholders=set())

        messages.append({"role": "system", "content": escaped_sys})

        # 3) Insérer l'historique (placeholder)
        messages.append(MessagesPlaceholder(variable_name="history"))

        # 4) Insérer le(s) input utilisateur
        # On attend un placeholder 'user_input' dans user_inputs
        raw_user = user_inputs.get("user_input", "")
        escaped_user = self.escape_braces(raw_user, keep_placeholders={"user_input"})
        messages.append({"role": "user", "content": escaped_user})

        # 5) Construire le ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages(messages)

        return prompt

    def _get_history_fn(self) -> Callable[[int], SimpleChatHistory]:

        def get_history(session_id: int) -> SimpleChatHistory:
            db_msgs = self.session_mgr.get_messages(session_id)
            serial = [{"role": msg.sender, "content": msg.content} for msg in db_msgs if msg.sender in ("user", "llm")]
            return SimpleChatHistory(serial)

        return get_history

    def run_with_history(
        self,
        llm_runnable: Runnable,
        prompt: ChatPromptTemplate,
        session_id: int,
        user_input: str,
    ) -> str:
        """
        Envelop an LLM Langchain in a Runnablewithmessagehistory
        To inject history and generate the answer.

        Args:
            llm_runnable: Langchain LLM Instance (ex: Ollamallm) or Runnable already ready.
            prompt: ChatPromptTemplate returned by build_prompt.
            session_id: Identifier of the current session.
            user_input: text sent by the user.

        Returns:
            Answer generated by the LLM (STR).
        """
        chain = prompt | llm_runnable

        chain_with_history = RunnableWithMessageHistory(
            chain,
            get_session_history=self._get_history_fn(),
            input_messages_key="user_input",
            history_messages_key="history",
            config_key="configurable",
        )

        result = chain_with_history.invoke(
            {"user_input": user_input},
            config={"configurable": {"session_id": session_id}},
        )

        return getattr(result, "text", str(result))


class RAGPromptManager:
    """
    Built prompts enriched by RAG for user requests.
    """

    def __init__(self, config: RAGConfig):
        self.config = config

    def build_rag_prompt(self, base_system: str, query: str, chunks: List[Dict]) -> str:
        """
        Concatene prompt as follows:
        1) Header that explains to the LLM that this is a RAG context.
        2) Inclusion of chunks (text + path/file) sorted by relevance.
        3) User request.

        Returns the full prompt in string.
        """
        # 1) En-tête
        header = (
            "You are an assistant specializing in context analysis.\n"
            f"{base_system}\n"
            "Use the following extracts to respond precisely :\n\n"
        )

        # 2) Assemblage des chunks
        context_blocks = []
        for idx, chunk in enumerate(chunks, start=1):
            meta = chunk.get("metadata", {})
            path = meta.get("path", "unknown")
            snippet = chunk.get("text", "").strip()
            context_blocks.append(f"== Extrait {idx} ({path}) ==\n{snippet}\n")
        context = "\n".join(context_blocks)

        # 3) Requête utilisateur finale
        query_section = f"Request:\n{query}\n"

        # Créer le prompt final
        prompt = f"{header}{context}\n\n{query_section}"
        return prompt
