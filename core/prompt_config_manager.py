import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TypedDict


# définition du type
class PromptConfigDefaults(TypedDict):
    description: str
    temperature: float
    top_k: int
    repeat_penalty: float
    top_p: float
    min_p: float
    default_max_tokens: int


CONFIG_DIR = Path("core")
DEFAULT_LANG = "en"
DEFAULT_CONFIG_PATH = CONFIG_DIR / f"prompt_config_defaults_{DEFAULT_LANG}.json"


class PromptConfigManager:
    """manages the config prompt defaults
    loads and saves PromptConfigDefaultsonfigs,"""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize with a personalized file path if specified."""
        self._configs: dict[str, PromptConfigDefaults] = {}
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._load_configs()

    def _load_configs(self):
        """Loads configurations from the JSON file. Returns an insertion-ordered dict"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._configs = json.load(f)
        else:
            self._configs = {}

    def _save_configs(self):
        """Back up configurations in the JSON file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._configs, f, indent=2, ensure_ascii=False)

    # gestion de la langue des prompts
    def available_languages(self) -> dict[str, Path]:
        """
        Detect available prompt config files.
        Files must match pattern: prompt_config_defaults_XX.json
        Returns mapping { "en": Path(...), "fr": Path(...),...}
        """
        langs: dict[str, Path] = {}
        for file in CONFIG_DIR.glob("prompt_config_defaults_*.json"):
            lang_code = file.stem.split("_")[-1]  # récupère "en", "fr", et d'autres à venir si...
            langs[lang_code] = file
        return langs

    def load_language(self, lang: str):
        """
        Reload configs from the file matching the lang code.
        """
        available = self.available_languages()
        if lang not in available:
            raise ValueError(f"Language '{lang}' not available. Found: {list(available.keys())}")
        self.config_path = available[lang]
        # print("chemin de self.config_path : ", self.config_path)
        self._load_configs()

    def get_current_language(self) -> str:
        """
        Return the current language code (e.g. 'en', 'fr').
        """
        return self.config_path.stem.split("_")[-1]

    def set_current_language(self, lang: str):
        """
        Change the current language and reload configs.
        """
        self.load_language(lang)

    # Méthodes de base
    def get_all(self) -> dict[str, PromptConfigDefaults]:
        """Returns all configurations."""
        return self._configs

    def get_types(self) -> list[str]:
        """Return the names of the configurations available."""
        return list(self._configs.keys())

    def get_items(self) -> dict[str, str]:
        """Return the descriptions of the configurations."""
        return {name: config["description"] for name, config in self._configs.items()}

    # Méthodes de recherche
    def get_config(self, prompt_name: str) -> PromptConfigDefaults | None:
        """Returns a specific configuration by its name."""
        return self._configs.get(prompt_name, {})

    def get_hierarchy(self) -> Dict[str, Dict[str, object]]:
        """
        Build a hierarchy based on the first word of each prompt name.
        The order of the categories follows the order of appearance in the
        original JSON file. The description is already attached, therefore the UI never has to call.
        TODO refresh from toolbar when "+ New Role" function's purpose is accepted
        Return type :
        {
            "Category": {
                "base": (name, description) | None,
                "children": [(name, description), ...]
            },
            ...
        }
        """
        hierarchy: Dict[
            str, Dict[str, Tuple[Optional[Tuple[str, str]], List[Tuple[str, str]]]]
        ] = {}

        # Parcours dans l'ordre d'insertion du JSON
        for name, cfg in self._configs.items():
            first_word, *rest = name.split(" ", 1)
            category = first_word

            # Initialise si besoin
            if category not in hierarchy:
                hierarchy[category] = {"base": (None, None), "children": []}

            entry = (name, cfg["description"])

            # Prompt exactement égal au premier mot → base
            if not rest:
                hierarchy[category]["base"] = entry
            else:
                hierarchy[category]["children"].append(entry)

        return hierarchy

    def add_new_prompt(self, name: str, config: PromptConfigDefaults):
        """Add a new configuration if it does not exist."""
        if name in self._configs:
            return False
        self._configs[name] = config
        self._save_configs()
        return True

    def remove_prompt(self, name: str):
        """Deletes an existing configuration.
        # TODO to be implemented later in GUI
        """
        if name not in self._configs:
            return False
        del self._configs[name]
        self._save_configs()
        return True

    def search_configs(self, keyword: str) -> dict[str, PromptConfigDefaults]:
        """Search configurations containing a keyword in their description.
        # TODO to be implemented later in GUI
        """
        return {
            name: config
            for name, config in self._configs.items()
            if keyword.lower() in config["description"].lower()
        }
