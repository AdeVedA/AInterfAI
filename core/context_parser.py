import configparser
import fnmatch
import io
import json
import os
import threading
import tokenize
from pathlib import Path
from typing import Dict, List, Optional, Set

import tiktoken
from dotenv import load_dotenv
from tiktoken.core import Encoding

from core.rag.file_loader import extract_text


class ParserConfig:
    """
    Loads and manages the config (INI) for the Context Parser.
    Sections available (with default values in Defaults):
      - General.history_max
      - Paths.history
      - Exclude.dirs, Exclude.files
      - Extensions.allowed
      - Options.use_gitignore
      - Token.model
    """

    DEFAULT_CONFIG_NAME = "default"
    DEFAULTS = {
        "General": {"history_max": "10"},
        "Paths": {"history": ""},
        "Extensions": {
            "allowed": ".py .js .jsx .tsx .ts .html .css .qss .json .cpp .c .java .go .rs .swift .php .sql .sh .ps1 "
            ".rb .pl .scala .dart .kt .swift .xml .yaml .yml .pdf .docx .pptx .rtf .txt"
        },
        "Exclude": {
            "dirs": ".git env venv .env .venv .hg .svn .idea .vscode node_modules dist build target out logs temp tmp "
            "__pycache__ .pytest_cache *coverage* *flake8* *storage*",
            "files": "LICENSE README.md CONTRIBUTING.md INSTALL.md CHANGELOG.md Dockerfile Makefile requirements.txt "
            "setup.py pom.xml composer.json package-lock.json package.json Gemfile gemspec *__init__* *bootstrap* "
            "*.jpg *.jpeg *.png *.mp4 *.mov",
        },
        "Options": {"use_gitignore": "yes"},
        "Token": {"model": "gpt-4"},
    }

    def __init__(self, config_path: Optional[Path] = None, config_name: Optional[str] = None):
        # fichier json à côté du module
        self.config_path = Path(config_path or Path(__file__).parent / "context_parser_config.json")
        self.config_name = config_name or self.DEFAULT_CONFIG_NAME
        if not self.config_path.exists():
            self._write_defaults()
        self._cfg_dict = {}
        self._load_json_config()

    def _load_json_config(self):
        """Setter of all configs dict self._cfg_dict from json, with defaults fallbacks"""
        if not self.config_path.exists():
            self._cfg_dict = {"configs": {self.config_name: self.DEFAULTS}}
            self.save()
        else:
            try:
                self._cfg_dict = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            except Exception as e:
                print(f"JSON reading error : {e}")
                self._cfg_dict = {"configs": {}}
        if self.config_name not in self._cfg_dict["configs"]:
            self._cfg_dict["configs"][self.config_name] = self.DEFAULTS

    def save(self):
        """Write all configurations back to in the JSON file"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self._cfg_dict, indent=2), encoding="utf-8")

    def restore_defaults(self):
        """Reset only the active configuration to its default values."""
        self._cfg_dict["configs"][self.config_name] = self.DEFAULTS.copy()
        self.save()

    def get_default_config(self, config_name: str) -> dict:
        """Returns the default values for a given configuration name."""
        return self.DEFAULTS

    def _write_defaults(self):
        cfg = configparser.ConfigParser()
        for section, values in self.DEFAULTS.items():
            cfg[section] = values
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            cfg.write(f)

    @property
    def _cfg(self):
        return self._cfg_dict["configs"][self.config_name]

    @property
    def history_max(self) -> int:
        return int(self._cfg.get("General", {}).get("history_max", 10))

    @property
    def history(self) -> List[str]:
        raw = self._cfg.get("Paths", {}).get("history", "")
        return [p for p in raw.split("|") if p]

    def add_to_history(self, path: str):
        h = self.history
        if path in h:
            h.remove(path)
        h.insert(0, path)
        h = h[: self.history_max]
        self._cfg.setdefault("Paths", {})["history"] = "|".join(h)
        self.save()

    @property
    def allowed_extensions(self) -> Set[str]:
        ext = self._cfg.get("Extensions", {}).get("allowed", "")
        return set(ext.split())

    @property
    def exclude_dirs(self) -> Set[str]:
        return set(self._cfg.get("Exclude", {}).get("dirs", "").split())

    @property
    def exclude_files(self) -> Set[str]:
        return set(self._cfg.get("Exclude", {}).get("files", "").split())

    @property
    def use_gitignore(self) -> bool:
        return self._cfg.get("Options", {}).get("use_gitignore", "yes").lower() == "yes"

    @property
    def token_model(self) -> str:
        return self._cfg.get("Token", {}).get("model", "gpt-4")


class TooManyFilesError(RuntimeError):
    """Raised when the parser would return more files than the allowed maximum."""

    pass


class ContextParser(ParserConfig):
    """
    Inherited from ParserConfig, adds :
      - list_files(base_dir): Inclusion/exclusion according to the config
      - count_tokens(path): tiktoken tokens counting for files
      - count_tokens_from_text(txt) : tiktoken tokens counting for text
      - generate_markdown(files, mode): code vs documents
      - save_markdown(markdown, output_path)
    """

    _lang_map = {
        "c++": "cpp",
        "c#": "csharp",
        "f#": "fsharp",
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "tsx": "tsx",
        "jsx": "jsx",
        "html": "html",
        "css": "css",
        "qss": "css",
        "json": "json",
        "cpp": "cpp",
        "c": "c",
        "java": "java",
        "go": "go",
        "rs": "rust",
        "swift": "swift",
        "php": "php",
        "sql": "sql",
        "sh": "bash",
        "bat": "batch",
        "ps1": "powershell",
        "rb": "ruby",
        "pl": "perl",
        "scala": "scala",
        "dart": "dart",
        "kt": "kotlin",
        "md": "markdown",
        "xml": "xml",
        "yaml": "yaml",
        "yml": "yaml",
        "csv": "csv",
        "ini": "ini",
        "cfg": "ini",
        "conf": "ini",
        "log": "text",
        "txt": "text",
    }
    DEFAULT_MAX_FILES = 3000

    def __init__(
        self,
        config_path: Optional[Path] = None,
        config_name: Optional[str] = "default",
        max_files: Optional[int] = None,
    ):
        super().__init__(config_path, config_name)
        self.max_files: int = max_files or self.DEFAULT_MAX_FILES
        self._token_enc = None
        self._token_lock = threading.Lock()
        self._token_cache: Dict[Path, int] = {}
        # Charger la variable d'env depuis .env (à la racine)
        project_root = Path(__file__).parent.parent
        load_dotenv(dotenv_path=project_root / ".env")
        self.config_name = config_name
        # Définir la variable d'environnement pour tiktoken
        self.encoding_path = os.getenv("TIKTOKEN_ENCODING_PATH")
        if self.encoding_path:
            self.encoding_path = str(Path(self.encoding_path).resolve())
            os.environ["TIKTOKEN_CACHE_DIR"] = self.encoding_path

    def _get_encoder(self) -> Encoding:
        """return local encoder for tiktoken tokens counting"""
        if self._token_enc is None:
            self._token_enc = tiktoken.get_encoding("cl100k_base")
        return self._token_enc

    def count_tokens(self, filepath: Path) -> int:
        """Return the number of tokens of a file, with cache."""
        if filepath in self._token_cache:
            return self._token_cache[filepath]
        text = filepath.read_text(encoding="utf-8", errors="ignore")
        n = len(self._get_encoder().encode(text, disallowed_special=()))
        with self._token_lock:
            self._token_cache[filepath] = n
        return n

    def count_tokens_from_text(self, text: str) -> int:
        """Count tokens from a string (e.g., user input)."""
        return len(self._get_encoder().encode(text))

    def _read_gitignore(self, base: Path) -> List[str]:
        """returns a list of gitignore exclusions lines or [None]"""
        gitignore = base / ".gitignore"
        if not self.use_gitignore or not gitignore.exists():
            return []
        return [
            line.strip()
            for line in gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]

    def list_files(self, base_dir: Path, raise_on_limit: bool = True) -> List[Path]:
        """
        Travels recursively `base_dir`, applies inclusions/exclusions,
        and returns the ordered list of at most `self.max_files` paths to be included.
        If the number of files exceeds `self.max_files':

        * `raise_on_limit = true` → will raise` toomanyfileserror '(current logic)
        * `raise_on_limit = false` → will only return `Self.max_files" first files (all the others are truncated).
        """
        base = Path(base_dir)
        git_pats = self._read_gitignore(base)
        out: List[Path] = []

        def walk(d: Path):
            nonlocal out
            for child in sorted(d.iterdir()):
                if len(out) > self.max_files:
                    return
                if child.is_dir():
                    if any(fnmatch.fnmatch(child.name, pat) for pat in self.exclude_dirs):
                        continue
                    walk(child)
                else:
                    suf = child.suffix.lower()
                    if (
                        ".*" in self.allowed_extensions or suf in self.allowed_extensions
                    ) and child.name not in self.exclude_files:
                        rel = child.relative_to(base)
                        if not any(fnmatch.fnmatch(str(rel), pat) for pat in git_pats):
                            out.append(child)

        walk(base)
        # Si on a coupé le parcours, on signale le dépassement
        if len(out) > self.max_files:
            if raise_on_limit:
                raise TooManyFilesError(
                    f"More than {self.max_files:,} files match the current configuration.\n"
                    "Option 1 : narrow the filters (inclusions/exclusions) of the current "
                    "parser pressing '⚙️ Config' in the Context panel.\n"
                    "Option 2 (careful): change the limit DEFAULT_MAX_FILES in context_parser.py and launch again\n"
                    f"Option 3 we can show only the first ones... within the {self.max_files:,} limit."
                )
            return out[: self.max_files]  # Tronquer
        return out

    # TODO regarder comment gérer le nettoyage et les cas docs/code
    @staticmethod
    def _strip_comments_and_docstrings(source: str) -> str:
        """
        Delete Comments and Docstrings (chains at the head of the block).
        """
        io_obj = io.StringIO(source)
        out_tokens: List[str] = []
        prev_tok = tokenize.INDENT
        last_row, last_col = -1, 0

        for toktype, tok, (srow, scol), (erow, ecol), _ in tokenize.generate_tokens(io_obj.readline):
            if toktype == tokenize.COMMENT:
                continue
            if toktype == tokenize.STRING and prev_tok in (tokenize.INDENT, tokenize.NEWLINE):
                continue
            if srow > last_row:
                last_col = 0
            if scol > last_col:
                out_tokens.append(" " * (scol - last_col))
            out_tokens.append(tok)
            prev_tok, last_row, last_col = toktype, erow, ecol

        return "".join(out_tokens)

    def generate_markdown(self, files: List[Path], mode: str = "Code") -> str:
        """
        Build a Markdown of context :
          - **Structure**: Relative file list
          - **Content**:
              * Documents -> Inventory + nbr tokens
              * Code      -> Inclusion of the Clean Code
        """
        import os

        from core.rag.file_loader import SUPPORTED

        # Tenter le plus petit dossier commun
        if files:
            # commonpath renvoie un str
            common = Path(os.path.commonpath([str(f.parent) for f in files]))
            base_dir = common
        else:
            base_dir = Path.cwd()

        # Structure
        struct_lines = ["**Structure**", ""]
        for f in files:
            try:
                rel = f.relative_to(base_dir)
            except ValueError:
                rel = Path(os.path.relpath(str(f), str(base_dir)))
            struct_lines.append(f"- {rel}")
        struct_section = "\n".join(struct_lines) + "\n\n"

        # Contenu
        content = ["**Content**", ""]
        for f in files:
            rel = f.relative_to(base_dir)
            if mode.lower().startswith("doc"):
                tok = self.count_tokens(f)
                content.append(f"- **{rel}** ({tok} tokens)")
            else:
                raw = f.read_text(encoding="utf-8", errors="ignore")
                # Si c'est un format supporté, on extrait proprement
                if f.suffix.lower() in SUPPORTED:
                    raw = extract_text(f)
                else:
                    raw = f.read_text(encoding="utf-8", errors="ignore")

                try:
                    # TODO look into how to handle les diffréents cases
                    # clean = self._strip_comments_and_docstrings(raw)
                    clean = raw
                except tokenize.TokenError as e:
                    clean = f"# Error while parsing {f.name}:\n# {str(e)}"

                lang = self._lang_map.get(f.suffix.lstrip("."), "text")
                content += [f"**{rel}**", f"```{lang}", clean, "```", ""]

        return struct_section + "\n".join(content)

    def save_markdown(self, markdown: str, output_path: Path | str) -> None:
        """
        Back up the Markdown generated in a file.
        """
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(markdown)
