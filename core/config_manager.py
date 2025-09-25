from core.database import SessionLocal
from core.models import PromptConfig


class ConfigManager:
    """
    Manager for loading and saving PromptConfig entries.
    """

    def __init__(self):
        # Create a new DB session for operations
        self.db = SessionLocal()

    def load_role_config(self, llm_name: str, prompt_type: str) -> PromptConfig | None:
        """
        Retrieves existing config for given LLM and prompt type.
        Returns None if not found.
        """
        return (
            self.db.query(PromptConfig)
            .filter_by(llm_name=llm_name, prompt_type=prompt_type)
            .first()
        )

    def save_role_config(self, llm_name: str, prompt_type: str, params: dict) -> PromptConfig:
        """
        Creates or updates a PromptConfig using params dict.
        Returns the persisted PromptConfig.
        """
        cfg = self.load_role_config(llm_name, prompt_type)
        if not cfg:
            # Instantiate new config if absent
            cfg = PromptConfig(llm_name=llm_name, prompt_type=prompt_type, **params)
            self.db.add(cfg)
        else:
            # Update existing config fields
            for key, value in params.items():
                setattr(cfg, key, value)
        # Commit transaction, refresh instance and return config
        self.db.commit()
        # Recharge cfg pour récupérer par exemple les valeurs par défaut générées en base
        self.db.refresh(cfg)
        return cfg
