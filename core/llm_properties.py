import json
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Tuple

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models import LLMProperties


class LLMPropertiesManager:
    """Synchronize the LLMProperties table with the models present on Ollama."""

    def __init__(
        self,
        db: Session,
        ollama_url: str = "http://localhost:11434",
        sync_time: timedelta = timedelta(days=99),
    ):
        self.db = db
        self.base_url = ollama_url.rstrip("/")
        self.sync_time = sync_time
        self.last_sync: datetime | None = None

    def _get_oldest_datetime(self):
        """
        Retrieves the oldest (earliest) datetime from the 'last_checked' column.
        """
        self.last_sync = self.db.query(func.min(LLMProperties.last_checked)).scalar()

    def needs_initial_sync(self) -> bool:
        """Returns True when LLMProperties contains no rows/table is empty (first-run case)"""
        return self.db.query(LLMProperties.id).first() is None

    def _fetch_ollama_catalog(self) -> dict[str, int]:
        """
        GET /api/tags and returns a mapping {model_name: size_in_bytes}.
        """
        resp = requests.get(f"{self.base_url}/api/tags")
        resp.raise_for_status()
        payload = resp.json()
        return {m["name"]: m.get("size", 0) for m in payload.get("models", [])}

    def sync_missing_and_refresh(
        self,
        force_refresh: bool = False,
        progress_callback: Callable[[str], None] | None = None,
    ) -> List[dict]:
        """
        Public entry point that delegates to three private helpers that can also be called individually.
        fetch the Ollama catalog once, inserts new ollama models, if force_refresh compares Ollama and DB values
        Returns : List[dict]
            Each element has the shape::
                {
                    "model": <str>,
                    "new_data": <flat dict from Ollama>,
                    "diff": {"field": (old_val, new_val), ...}
                }
            The list is empty when `force_refresh` is False or nothing changed.
        """
        ollama_catalog = self._fetch_ollama_catalog()

        # insére tout model présent chez Ollama mais manquant en DB
        missing_models = self._insert_missing_models(ollama_catalog, progress_callback)

        # Si l'utilisateur a demandé un full refresh -> compare les paramètres existants DB/Ollama
        if force_refresh:
            return self._compare_existing_rows(ollama_catalog, missing_models, progress_callback)
        return []  # pas de diffs si on a juste fait une insertion de nouveau modèle

    def _insert_missing_models(
        self,
        ollama_catalog: dict[str, int],
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        """
        Scan Ollama, compare with the DB and INSERT every model that is missing.
        Used by ``sync_missing_and_refresh`` *and* can be called on its own.
        """
        self.db.expire_all()
        db_rows = {r.model_name: r for r in self.db.query(LLMProperties).all()}
        now = datetime.now(timezone.utc)

        missing_models = set(ollama_catalog) - set(db_rows)
        if not missing_models:
            return missing_models

        if progress_callback:
            progress_callback(f"Inserting {len(missing_models)} new model(s)… " f"{', '.join(sorted(missing_models))}")

        for name in missing_models:
            show_info = self._fetch_show_info(name)
            flat = self._extract_model_info(name, show_info)

            props = LLMProperties(
                model_name=name,
                size=round(int(ollama_catalog.get(name, 0)) / (1024**3), 2),
                context_length=flat["context_length"],
                capabilities=flat["capabilities"],
                temperature=flat["temperature"],
                top_k=flat["top_k"],
                repeat_penalty=flat["repeat_penalty"],
                top_p=flat["top_p"],
                min_p=flat["min_p"],
                architecture=flat["architecture"],
                parameter_size=flat["parameter_size"],
                quantization_level=flat["quantization_level"],
                template=flat["template"],
                last_checked=now,
            )
            self.db.add(props)

        self.db.commit()
        return missing_models

    def _compare_existing_rows(
        self, ollama_catalog: dict[str, int], missing_models: set[str], progress_callback: Callable[[str], None] | None = None
    ) -> List[dict]:
        """
        Compare every DB model row with model data from Ollama and build the diff list.
        """
        from concurrent.futures import ThreadPoolExecutor

        if ollama_catalog is None:
            ollama_catalog = self._fetch_ollama_catalog()
        self.db.expire_all()
        db_rows = {r.model_name: r for r in self.db.query(LLMProperties).all()}
        total = len(db_rows)

        def _normalise(val):
            """Normalise a column/value so that two semantically equal values compare equal.
            Used by sync_missing_and_refresh() when force_refresh=True."""
            # Nombres – garder tels quels (int/float)
            if isinstance(val, (int, float)):
                return val
            # JSON (capabilities)
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        return sorted(parsed)
                except Exception:
                    pass  # not JSON -> fall through
            if isinstance(val, list):
                return sorted(val)
            # Template – normalise line endings and strip surrounding whitespace
            if isinstance(val, str) and ("\n" in val or "\r" in val):
                return val.replace("\r\n", "\n").replace("\r", "\n")
            # if val is None:
            #     return 0.0
            # Tout le reste (bool, str sans newlines) – garder tel quel
            return val

        def _process_one(name: str, db_obj):
            """fetch info, build diff and return a dict or None."""
            show_info = self._fetch_show_info(name)
            if not show_info:
                return None
            fresh_flat = self._extract_model_info(name, show_info)

            row_diff: dict[str, Tuple[any, any]] = {}
            for field in [
                "size",
                "context_length",
                "capabilities",
                "temperature",
                "top_k",
                "repeat_penalty",
                "top_p",
                "min_p",
                "architecture",
                "parameter_size",
                "quantization_level",
                "template",
            ]:
                old_val = getattr(db_obj, field)
                new_val = round(int(ollama_catalog.get(name, 0)) / (1024**3), 2) if field == "size" else fresh_flat[field]
                if _normalise(old_val) != _normalise(new_val):
                    row_diff[field] = (old_val, new_val)

            return {"model": name, "new_data": fresh_flat, "diff": row_diff} or None

        def _make_task(name: str, db_obj, idx: int):
            """Wrap the original processing (so we could emit a per-model progress line.)"""

            def task():
                # émis à partir du du thread d'arrière-plan;
                if progress_callback:
                    progress_callback(f"Comparing {name} ({idx}/{total})")
                return _process_one(name, db_obj)

            return task

        diffs: List[dict] = []
        # jusqu'à 8 requêtes en parallèle
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {}
            print("Comparing models DB/Ollama data : ")
            for i, (model_name, obj) in enumerate(db_rows.items(), start=1):
                print(i, " : ", model_name)
                futures[pool.submit(_make_task(model_name, obj, i))] = (model_name, i)
            for fut, (model_name, idx) in futures.items():
                diff_entry = fut.result()
                if diff_entry:
                    diffs.append(diff_entry)
                    if progress_callback:
                        progress_callback(f"Processed {model_name} ({idx}/{total})")

        # update la colonne `last_checked` pour chaque rangée de modèle changée (inserted + diff‑ed)
        if missing_models or diffs:
            affected = list(missing_models) + [d["model"] for d in diffs]
            now = datetime.now(timezone.utc)
            self.db.query(LLMProperties).filter(LLMProperties.model_name.in_(affected)).update(
                {LLMProperties.last_checked: now}, synchronize_session=False
            )
            self.db.commit()
        return diffs

    def edit_model_parameters(self, model_name: str) -> dict[str, any]:
        """
        Return the current values stored in the `local database` for `model_name`.
        The result is a flat dictionary that can be edited by `ModelDiffDialog`.
        Fields that are not editable (size, capabilities, architecture,
        parameter_size, quantization_level) are removed from the dict.
        """
        obj = self.db.query(LLMProperties).filter_by(model_name=model_name).one_or_none()
        if obj is None:
            raise KeyError(f"Model '{model_name}' not found in the local DB")

        flat: dict[str, any] = {
            "model_name": obj.model_name,
            "size": obj.size,
            "context_length": obj.context_length,
            "capabilities": (json.loads(obj.capabilities) if isinstance(obj.capabilities, str) else obj.capabilities),
            "temperature": obj.temperature,
            "top_k": obj.top_k,
            "repeat_penalty": obj.repeat_penalty,
            "top_p": obj.top_p,
            "min_p": obj.min_p,
            "architecture": obj.architecture,
            "parameter_size": obj.parameter_size,
            "quantization_level": obj.quantization_level,
            "template": obj.template,
        }

        for excluded in ("size", "capabilities", "architecture", "parameter_size", "quantization_level"):
            flat.pop(excluded, None)
        return flat

    def update_properties(
        self,
        model_name: str,
        field_value_dict: dict[str, str],
    ) -> None:
        """
        Apply the selected fields from fresh_flat to the row identified by
        model_name. The method rounds the size to two decimals (the same
        format we store in the DB) and updates last_checked.
        """
        obj = self.get_properties(model_name)
        if obj is None:
            # Protection au cas où
            return

        for field, new_value in field_value_dict.items():
            if field == "size":
                # fresh_flat['size'] is already a GB float
                setattr(obj, field, round(new_value, 2))
            else:
                setattr(obj, field, new_value)

        obj.last_checked = datetime.now(timezone.utc)
        self.db.commit()

    def _fetch_show_info(self, model_name: str) -> dict:
        """GET /api/show for a single model."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/show",
                json={"model": model_name},
                timeout=10,
            )
            resp.raise_for_status()  # raise exception pour status 40x / 50x
            return resp.json()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                # Model manquant – "pas disponible chez Ollama".
                return None
            # Tout autre problème (network, 500…) raise.
            raise

    def _extract_model_info(self, model_name: str, info: dict) -> dict:
        """
        Transforms Ollama's raw response (/API/show) into usable flat dict
        to supply LLMPROPERTIES table.
        """
        # Template
        template = info.get("template", "")

        # Paramètres recommandés
        parameters = {}
        param_str = info.get("parameters", "")
        for line in param_str.splitlines():
            if "stop" in line:
                continue
            # on détecte une tabulation multiple comme séparateur
            if "        " in line:
                key, value = line.split("        ", 1)
                key = key.strip()
                value = value.strip()
                try:
                    value = float(value)
                except ValueError:
                    pass
                parameters[key] = value

        # Family / architecture / sizes
        details = info.get("details", {})
        family = details.get("family", "Unknown Family")
        architecture = info.get("model_info", {}).get("general.architecture", "Unknown Architecture")
        parameter_size = details.get("parameter_size", "Unknown Size")
        quant_level = details.get("quantization_level", "Unknown Quant_Level")

        # Context length
        ctx_len = info.get("model_info", {}).get(f"{family}.context_length", "Unknown Context Length")

        # Capabilities & model size
        capabilities = info.get("capabilities", [])
        try:
            model_size = int(info.get("size", 0))
        except (TypeError, ValueError):
            model_size = 0.0  # Fallback value
        size_gb = round(model_size / (1024**3), 2)

        return {
            "model_name": model_name,
            "size": size_gb,
            "context_length": int(ctx_len),
            "capabilities": capabilities,
            "temperature": parameters.get("temperature"),
            "top_k": parameters.get("top_k"),
            "repeat_penalty": parameters.get("repeat_penalty"),
            "top_p": parameters.get("top_p"),
            "min_p": parameters.get("min_p"),
            "architecture": architecture,
            "parameter_size": parameter_size,
            "quantization_level": quant_level,
            "template": template,
        }

    def get_llm_params(self, model_name: str) -> dict:
        """Only returns the non-NULL parameters of a given model."""
        params = select(
            LLMProperties.temperature,
            LLMProperties.top_k,
            LLMProperties.repeat_penalty,
            LLMProperties.top_p,
            LLMProperties.min_p,
        ).where(LLMProperties.model_name == model_name)

        result = self.db.execute(params).first()
        if not result:
            return {}

        keys = ["temperature", "top_k", "repeat_penalty", "top_p", "min_p"]

        # Filtrer les valeurs NULL
        return {k: v for k, v in zip(keys, result) if v is not None}

    def merge_with_defaults(self, role_defaults: dict, model_name: str) -> dict:
        """when loading a Role with LLM, overrides the Role hyperparameters with default LLM ones"""
        overrides = self.get_llm_params(model_name)
        return {**role_defaults, **overrides}

    def get_embeddings_list(self):
        """
        Returns the list of LLM names that capabilities contains 'embedding'.
        Optimized request to recover only the Model_Name column.
        """
        rows = self.db.query(LLMProperties.model_name).filter(LLMProperties.capabilities.contains(["embedding"])).all()
        return [r[0] for r in rows]

    def get_properties(self, model_name: str) -> "LLMProperties | None":
        """
        Return the ORM row for model_name (or `None` if it does not exist).
        """
        return self.db.query(LLMProperties).filter_by(model_name=model_name).one_or_none()
