from core.database import SessionLocal
from core.models import RoleConfig


class ConfigManager:
    """
    Manager for loading and saving RoleConfig entries.
    """

    def __init__(self):
        # Créer une nouvelle session de base de données pour les opérations
        self.db = SessionLocal()

    def load_role_config(self, llm_name: str, role_type: str) -> RoleConfig | None:
        """
        Retrieves existing config for given LLM and Role type.
        Returns None if not found.
        """
        return self.db.query(RoleConfig).filter_by(llm_name=llm_name, role_type=role_type).first()

    def save_role_config(self, llm_name: str, role_type: str, params: dict) -> RoleConfig:
        """
        Creates or updates a RoleConfig using params dict.
        Returns the persisted RoleConfig.
        """
        cfg = self.load_role_config(llm_name, role_type)
        if not cfg:
            # Instancier une nouvelle configuration en cas d'absence
            cfg = RoleConfig(llm_name=llm_name, role_type=role_type, **params)
            self.db.add(cfg)
        else:
            # Mettre à jour les champs de configuration existants
            for key, value in params.items():
                setattr(cfg, key, value)
        # Valider la transaction, actualiser l'instance et renvoyer la configuration
        self.db.commit()
        # Recharge cfg pour récupérer par exemple les valeurs par défaut générées en base
        self.db.refresh(cfg)
        return cfg
