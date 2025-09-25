# -*- coding: utf-8 -*-
from collections import defaultdict

from sqlalchemy import func

from core.database import SessionLocal
from core.models import Folder, Message, Session


class SessionManager:
    """
    Manager for creating sessions and appending messages.
    """

    def __init__(self):
        # Nouvelle session DB pour les opérations de session
        self.db = SessionLocal()

    def list_folders(self) -> list[Folder]:
        """Retourne tous les dossiers."""
        return self.db.query(Folder).order_by(Folder.created_at.desc()).all()

    def list_sessions(self) -> list[Session]:
        """
        Return all sessions ordered by creation date descending.
        """
        # print("Listing sessions...")
        sessions = self.db.query(Session).order_by(Session.created_at.desc()).all()
        # print(f"Sessions récupérées : {sessions}")
        return sessions

    def create_session(self, folder_id: int = None, session_name: str = None) -> Session:
        s = Session(
            session_name=session_name or "",
            folder_id=folder_id,
        )
        self.db.add(s)
        self.db.commit()
        # si aucun nom fourni, on génère "session_<id>"
        if not session_name:
            s.session_name = f"session_{s.id}"
            self.db.commit()
        self.db.refresh(s)
        return s

    def get_session(self, session_id: int) -> Session | None:
        """
        Return the full session object for the given ID.
        """
        return self.db.get(Session, session_id)

    def filter_sessions(self, filter_type: str) -> dict[str, list[Session]]:
        """
        Return a dict mapping in each category (prompt_type or llm_name)
        to the list of corresponding sessions, sorted by Timetamp descending
        from the last LLM message.

        If filter_type == 'Date', returns {'All': [Sessions sorted by creation date]}.
        """
        # Filtrer par date de création globale
        if filter_type == "Date":
            all_sessions = self.db.query(Session).order_by(Session.created_at.desc()).all()
            return {"All": all_sessions}

        # Sous-requête pour timestamp du dernier message LLM par session
        last_llm_ts = (
            self.db.query(
                Message.session_id.label("session_id"),
                func.max(Message.timestamp).label("last_ts"),
            )
            .filter(Message.sender == "llm")
            .group_by(Message.session_id)
            .subquery()
        )

        # Join pour récupérer la valeur de la clé triée
        rows = (
            self.db.query(Session, Message.llm_name, Message.prompt_type, last_llm_ts.c.last_ts)
            .join(last_llm_ts, Session.id == last_llm_ts.c.session_id)
            .join(
                Message,
                (Message.session_id == last_llm_ts.c.session_id)
                & (Message.timestamp == last_llm_ts.c.last_ts)
                & (Message.sender == "llm"),
            )
        )

        # Ordonner par la colonne demandée, puis par date desc
        key_col = Message.prompt_type if filter_type == "Prompt-type" else Message.llm_name
        ordered = rows.order_by(key_col, last_llm_ts.c.last_ts.desc()).all()

        # Regrouper dans un dict { clé -> [Session, ...] }
        grouped: dict[str, list[Session]] = defaultdict(list)
        for sess, llm_name, prompt_type, _ in ordered:
            key = prompt_type if filter_type == "Prompt-type" else llm_name
            grouped[key].append(sess)
        # print("Grouped sessions:", {k: len(v) for k, v in grouped.items()})
        return dict(grouped)

    def rename_session(self, session_id: int, new_name: str) -> None:
        s = self.db.get(Session, session_id)
        if s:
            s.session_name = new_name
            self.db.commit()

    def delete_session(self, session_id: int) -> None:
        s = self.db.get(Session, session_id)
        if s:
            self.db.delete(s)
            self.db.commit()

    def get_messages(self, session_id: int) -> list[Message]:
        if session_id is None:
            return []
        s = self.db.get(Session, session_id)
        return s.messages if s else []

    def add_message(
        self,
        session_id: int,
        sender: str,
        content: str,
        llm_name: str = None,
        prompt_type: str = None,
        config_id: int = None,
    ) -> Message:
        """
        Append a message to an existing session.
        Returns the persisted Message.
        """
        if session_id is None:
            raise ValueError("add_message() called without session_id.")
        # Pour les messages LLM, on complète les métadonnées
        kwargs = {}
        if sender == "llm":
            kwargs = dict(llm_name=llm_name, prompt_type=prompt_type, config_id=config_id)
        msg = Message(session_id=session_id, sender=sender, content=content, **kwargs)
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def update_message(self, message_id: int, new_content: str) -> None:
        """
        Update the content of a Message in the database.
        """
        msg = self.db.get(Message, message_id)
        if not msg:
            raise ValueError(f"Message with id {message_id} not found.")
        msg.content = new_content
        self.db.commit()

    def delete_message(self, message_id: int) -> None:
        """
        Delete a Message from the database.
        """
        msg = self.db.get(Message, message_id)
        if not msg:
            raise ValueError(f"Message with id {message_id} not found.")
        self.db.delete(msg)
        self.db.commit()

    def create_folder(self, name: str = None) -> Folder:
        """Creates a new folder and returns it."""
        from sqlalchemy import func

        if not name:
            # compter les dossiers existants pour incrémenter
            count = self.db.query(func.count(Folder.id)).scalar() or 0
            name = f"Dossier{count+1}"
        f = Folder(name=name)
        self.db.add(f)
        self.db.commit()
        return f

    def move_session_to_folder(self, session_id: int, folder_id: object) -> None:
        """
        Affects `folder_id` (or None) to the `folder_id` of the DB session.
        """
        print(f"Session moving {session_id} in folder {folder_id}")
        sess = self.db.get(Session, session_id)
        if not sess:
            print("Session not found.")
            raise ValueError(f"Session {session_id} not found")
        # si on passe folder_id, vérifier que le dossier existe
        if folder_id is not None:
            fld = self.db.get(Folder, folder_id)
            if not fld:
                raise ValueError(f"Folder {folder_id} not found")
        sess.folder_id = folder_id  # None ou int
        self.db.commit()

    def rename_folder(self, folder_id: int, new_name: str) -> None:
        f = self.db.get(Folder, folder_id)
        if not f:
            raise ValueError("Folder not found")
        f.name = new_name
        self.db.commit()

    def delete_folder(self, folder_id: int) -> None:
        f = self.db.get(Folder, folder_id)
        if not f:
            return
        # 1) détacher les sessions
        for sess in list(f.sessions):
            sess.folder_id = None
        # 2) supprimer le dossier
        self.db.delete(f)
        self.db.commit()
