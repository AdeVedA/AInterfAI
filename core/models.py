from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship  # , backref

# Base class for ORM models
Base = declarative_base()


class Folder(Base):
    """
    Represents an independent folder of sessions,
    which can contain other folders or sessions.
    """

    __tablename__ = "folder"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False)
    parent_id = Column(Integer, ForeignKey("folder.id"), nullable=True)
    parent = relationship("Folder", remote_side=[id], backref="children")
    sessions = relationship("Session", back_populates="folder", cascade="all, delete-orphan")


class Session(Base):
    """
    Represents a chat session. has an id, a name, a timestamp and can have a folder as parent.
    Can be a simple session or have "folder" of sessions (Parent_id managed).
    """

    __tablename__ = "session"
    id = Column(Integer, primary_key=True)
    session_name = Column(String, nullable=False, index=True)
    # created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default="CURRENT_TIMESTAMP",  # SQLite crée l’UTC à l’insertion
        default=datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    folder_id = Column(Integer, ForeignKey("folder.id"), nullable=True)

    folder = relationship("Folder", back_populates="sessions")
    messages = relationship(
        "Message",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.timestamp",
    )


class Message(Base):
    """
    A single message in (a history of) session.
    message sender = "user" => llm_name, role_type and config_id are NULL
    """

    __tablename__ = "message"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("session.id"), nullable=False, index=True)
    sender = Column(String, nullable=False)  # 'user' or 'llm'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False)

    llm_name = Column(String, ForeignKey("llm_properties.model_name"), nullable=True)
    role_type = Column(String, nullable=True)
    config_id = Column(Integer, ForeignKey("role_config.id"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(sender != 'llm') OR \
             (llm_name IS NOT NULL AND role_type IS NOT NULL AND config_id IS NOT NULL)",
            name="chk_message_llm_fields",
        ),
        Index("idx_message_config", "config_id"),
    )

    session = relationship("Session", back_populates="messages")
    config = relationship("RoleConfig")
    llm_properties = relationship("LLMProperties")


class RoleConfig(Base):
    """
    Stocke the overall configurations of Roles with their fundamental parameters.
    Unique by (llm_name, role_type).
    """

    __tablename__ = "role_config"
    id = Column(Integer, primary_key=True)
    llm_name = Column(String, nullable=False, index=True)
    role_type = Column(String, nullable=False, index=True)
    description = Column(Text)

    # Paramètres généraux du modèle
    temperature = Column(Float, default=0.7, nullable=False)
    top_k = Column(Integer, default=40, nullable=False)
    repeat_penalty = Column(Float, default=1.1, nullable=False)
    top_p = Column(Float, default=0.95, nullable=False)
    min_p = Column(Float, default=0.05, nullable=False)
    default_max_tokens = Column(Integer, default=16384, nullable=False)
    flash_attention = Column(Boolean, default=True)
    kv_cache_type = Column(String, default="f16")
    think = Column(String, default=None, nullable=True)

    __table_args__ = (UniqueConstraint("llm_name", "role_type", name="uix_llm_role"),)


class LLMProperties(Base):
    """Technical properties and limitations of LLM models retrieved through Ollama's API GET api/tags & POST api/show.

    Attributes:
        model_name (str): Unique identifier of the model (name:tag)
        context_length (int): Maximum length of supported context
        ...
    """

    __tablename__ = "llm_properties"
    model_name = Column(String, primary_key=True)

    size = Column(Float, nullable=False)
    context_length = Column(Integer, nullable=False)
    capabilities = Column(JSON, nullable=False)

    # recommended default parameters
    temperature = Column(Float, nullable=True)
    top_k = Column(Float, nullable=True)
    repeat_penalty = Column(Float, nullable=True)
    top_p = Column(Float, nullable=True)
    min_p = Column(Float, nullable=True)

    architecture = Column(String, nullable=False)
    parameter_size = Column(String, nullable=False)
    quantization_level = Column(String, nullable=False)
    template = Column(String, nullable=False)
    last_checked = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return (
            f"\nselected LLM Properties (AInterfAI DB side) :\nMODEL_name={self.model_name!r}, SIZE={self.size} GB"
            f"\ncontext_length={self.context_length}, capabilities={self.capabilities}\n"
            f"temp : {self.temperature}, top_k : {self.top_k}, repeat_penalty : {self.repeat_penalty}, "
            f"top_p : {self.top_p}, min_p : {self.min_p}\n"
        )
