from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from core.context_parser import ContextParser
from core.prompt_manager import PromptManager
from core.rag.handler import RAGHandler
from core.session_manager import SessionManager

from .msg_proc_utils import count_tokens_from_text, escape_braces


class PromptBuildResult(BaseModel):
    """Value returned by `UserMessageProcessor.build_prompt`."""

    formatted_prompt: str
    raw_template: object  # le PromptTemplate de LangChain (None pour mode=[0] OFF)
    history: List[object]  # liste de HumanMessage / AIMessage prêts à être stockés


class MissingConfigError(RuntimeError):
    """If no configuration is available."""


class UserMessageProcessor:
    """
    Class that orchestrates:
    - Context generation (FULL),
    - RAG Prompt construction (RAG),
    - the creation of the final prompt from a LangChain template,
    - Tokens counting.
    """

    def __init__(
        self,
        *,
        prompt_manager: PromptManager,
        context_parser: ContextParser,
        session_manager: SessionManager,
        rag_config: object,
    ) -> None:
        self.prompt_manager = prompt_manager
        self.context_parser = context_parser
        self.session_manager = session_manager
        self.rag_config = rag_config

        # Le handler RAG sera créé uniquement si le mode RAG est demandé
        self._rag_handler: Optional[RAGHandler] = None

    # Méthodes publiques – un point d'entrée par mode
    def process_off(
        self,
        session_id: int,
        user_text: str,
        config_id: int,
        current_system_prompt: str,
        llm_name: str,
    ) -> PromptBuildResult:
        """
        Mode OFF : No additional context
        We only build the prompt from the template.
        """
        return self._build_prompt(
            session_id=session_id,
            user_text=user_text,
            extra_context=None,
            config_id=config_id,
            current_system_prompt=current_system_prompt,
            llm_name=llm_name,
        )

    def process_full(
        self,
        session_id: int,
        user_text: str,
        selected_files: List[Path],
        config_id: int,
        current_system_prompt: str,
        llm_name: str,
    ) -> PromptBuildResult:
        """
        Mode FULL : generate a Markdown from the selected files,
        escape it and concaten it in a prompt.
        """
        markdown = self.context_parser.generate_markdown(selected_files, mode="Code")
        escaped = escape_braces(markdown) if markdown else ""
        full_context = "\n\n".join(
            (current_system_prompt, "### PROJECT CONTEXT ###", escaped, user_text)
        )
        return self._build_prompt(
            session_id=session_id,
            user_text=user_text,
            extra_context=full_context,
            config_id=config_id,
            current_system_prompt=current_system_prompt,
            llm_name=llm_name,
        )

    def ensure_rag_handler(self, session_id: int):
        """Ensure a RAGHandler exists for this session."""
        if self._rag_handler is None or self._rag_handler.session_id != session_id:
            self._rag_handler = RAGHandler(
                config=self.rag_config,
                session_id=session_id,
                ctx_parser=self.context_parser,
            )

    def ensure_and_get_rag_handler(self, session_id: int) -> RAGHandler:
        self.ensure_rag_handler(session_id)
        return self._rag_handler

    def process_rag(
        self,
        session_id: int,
        user_text: str,
        current_system_prompt: str,
        selected_files: List[Path],
        config_id: int,
        llm_name: str,
    ) -> PromptBuildResult:
        """
        Mode RAG : use `raghandler` to build the prompt (header +
        Extracts + query). The Raghandler` is re-initialized when
        changing session.
        """
        # 1 Instancier / ré-initialiser le handler si besoin
        if self._rag_handler is None or self._rag_handler.session_id != session_id:
            self._rag_handler = RAGHandler(
                config=self.rag_config,
                session_id=session_id,
                ctx_parser=self.context_parser,
            )

        # 2 Build the RAG prompt (may raise RuntimeError -> propagé à l'app)
        allowed_paths = [str(p) for p in selected_files]
        rag_prompt = self._rag_handler.build_rag_prompt(
            query=user_text,
            current_system_prompt=current_system_prompt,
            allowed_paths=allowed_paths,
        )

        return self._build_prompt(
            session_id=session_id,
            user_text=user_text,
            extra_context=rag_prompt,
            config_id=config_id,
            current_system_prompt=current_system_prompt,
            llm_name=llm_name,
        )

    # Méthode interne commune (construction du prompt + historique)
    def _build_prompt(
        self,
        *,
        session_id: int,
        user_text: str,
        extra_context: Optional[str],
        config_id: int,
        current_system_prompt: str,
        llm_name: str,
    ) -> PromptBuildResult:
        """
        Recovers the history from `SessionManager`,
        builds the `PromptTemplate` (via `PromptManager`),
        formats the prompt (with Fallback if a placeholder is missing),
        Returns the final text as well as the history already transformed.
        """

        # Historique (langchain messages)
        raw_messages = self.session_manager.get_messages(session_id)
        history = [
            HumanMessage(m.content) if m.sender == "user" else AIMessage(m.content)
            for m in raw_messages
        ]

        # Build the LangChain template
        prompt_template = self.prompt_manager.build_prompt(
            config_id=config_id,
            model_name=llm_name,
            current_system_prompt=current_system_prompt,
            user_inputs={"user_input": user_text},
        )

        # Try a normal `format_prompt`.  If a placeholder is missing,
        # fall back to a *safe* formatter that leaves the unknown token
        # unchanged ({{missing}}) – cela évite le crash UI.
        try:
            formatted = prompt_template.format_prompt(
                history=history, user_input=user_text
            ).to_string()
        except KeyError as ke:
            print("placeholders missing, fallback formatting with escaped placeholders")
            formatted = self._fallback_format(prompt_template, user_text, missing=ke.args[0])

        # Ajout du contexte supplémentaire (FULL / RAG) – si on a déjà
        # généré `extra_context` on l'utilise tel quel, sinon on garde le
        # prompt déjà formaté.
        if extra_context:
            final_prompt = extra_context
        else:
            final_prompt = formatted

        return PromptBuildResult(
            formatted_prompt=final_prompt,
            raw_template=prompt_template,
            history=history,
        )

    # Helper de secours pour le formatage quand un placeholder manque (du code avec {} etc)
    @staticmethod
    def _fallback_format(prompt_template, user_text: str, missing: str) -> str:
        """
        Built a text "safe" when a required placeholder is not provided.
        We keep the parts already formatted and replace the unknown placeholders by `{{placeholder}}`.
        """
        import re

        from langchain_core.prompts import (
            AIMessagePromptTemplate,
            HumanMessagePromptTemplate,
            MessagesPlaceholder,
            SystemMessagePromptTemplate,
        )

        def safe_replace(match):
            key = match.group(1)
            return {"user_input": user_text}.get(key, f"{{{{{key}}}}}")  # échappe les manquants

        formatted_parts = []
        for msg in prompt_template.messages:
            if isinstance(msg, MessagesPlaceholder):
                continue
            raw = getattr(msg.prompt, "template", str(msg))
            safe_text = re.sub(r"{([^{}]+)}", safe_replace, raw)

            if isinstance(msg, SystemMessagePromptTemplate):
                role = "System"
            elif isinstance(msg, HumanMessagePromptTemplate):
                role = "Human"
            elif isinstance(msg, AIMessagePromptTemplate):
                role = "AI"
            else:
                role = "Unknown"

            formatted_parts.append(f"{role}: {safe_text}")

        fallback = "\n\n".join(formatted_parts)
        return fallback

    # Méthodes utilitaires exposées (ex.: comptage de tokens)
    def count_tokens(self, text: str) -> int:
        """
        Wrapper around the Parser which counts the Tokens.
        Return 0 in case of error so that the GUI does not crash.
        """
        try:
            return count_tokens_from_text(text, context_parser=self.context_parser)
        except Exception:
            return 0
