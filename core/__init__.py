"""
Module: core/backend
Description: Business logic and persistence layer for LLM Roles,
sessions, context, rag, prompts, database and configurations.
This module is designed/separated to be imported as-is in a future project without PyQt.
Files:
    - database.py       : SQLAlchemy engine and session initialization
    - models.py         : ORM model definitions (RoleConfig, Session, Message)
    - config_manager.py : CRUD operations for Role/LLM configurations
    - session_manager.py: CRUD operations for chat sessions and messages
    - llm_manager.py    : Wrapper for Ollama + LangChain interactions
    - context_parser.py : Config and logic of folder parsing, files selection,
                          markdown generation or injection in prompt
    - rag/...           : RAG logic handler, file_loader, indexer and config
    - theme/            : theme management, color_palettes and themes.qss
    - tiktoken/         : local tiktoken model
    - message_manager/  : manager for input message/prompt building/handling (OFF, Full, RAG...)
"""
