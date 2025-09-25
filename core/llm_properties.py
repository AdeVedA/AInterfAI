from datetime import datetime, timedelta, timezone

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
        sync_time: timedelta = timedelta(days=30),
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

    def sync(self) -> None:
        """
        Synchronize the LLMPROPERTIES table with OLLAMA only if we have passed the TTL deadline.
        - Fetch the list of models via /api/tags
        - For each model absent from LLMPROPERTIES, makes an /api/show
        And insert the line in the base.
        """
        self._get_oldest_datetime()
        now = datetime.now(timezone.utc)
        if self.last_sync:
            self.last_sync = self.last_sync.astimezone(timezone.utc)
            if (now - self.last_sync) < self.sync_time:
                return  # on a sync récemment, on skip
        else:
            print("last_sync is None, skipping comparison.")

        # Liste des modèles Ollama
        resp = requests.get(f"{self.base_url}/api/tags")
        resp.raise_for_status()
        ollama_models = {m["name"]: m["size"] for m in resp.json().get("models", [])}

        # Modèles déjà en base
        existing = [r.model_name for r in self.db.query(LLMProperties.model_name).all()]

        # Nouveaux modèles à récupérer
        to_fetch = {k: v for k, v in ollama_models.items() if k not in existing}

        for model_name in to_fetch:
            show = requests.post(f"{self.base_url}/api/show", json={"model": model_name})
            show.raise_for_status()
            info = show.json()

            # Nettoyage des clés volumineuses
            for k in ("tensors", "modelfile", "license"):
                info.pop(k, None)

            # Extraction des infos du modèle en cours
            data = self._extract_model_info(model_name, info)
            # Insertion
            props = LLMProperties(
                model_name=data["model_name"],
                size=f"{int(to_fetch.get(model_name, 0)) / (1024**3):.2f}",
                context_length=data["context_length"],
                capabilities=data["capabilities"],
                temperature=data["temperature"] or None,
                top_k=data["top_k"] or None,
                repeat_penalty=data["repeat_penalty"] or None,
                top_p=data["top_p"] or None,
                min_p=data["min_p"] or None,
                architecture=data["architecture"],
                parameter_size=data["parameter_size"],
                quantization_level=data["quantization_level"],
                template=data["template"],
                last_checked=now,
            )
            self.db.add(props)
            print(f"Running sync of LLM Properties for model {model_name} ")
        print("End of LLM Properties synchronization for your Ollama models")
        if to_fetch:
            self.db.commit()

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
        architecture = info.get("model_info", {}).get(
            "general.architecture", "Unknown Architecture"
        )
        parameter_size = details.get("parameter_size", "Unknown Size")
        quant_level = details.get("quantization_level", "Unknown Quant_Level")

        # Context length
        ctx_len = info.get("model_info", {}).get(
            f"{family}.context_length", "Unknown Context Length"
        )

        # Capabilities & model size
        capabilities = info.get("capabilities", [])
        try:
            model_size = float(info.get("size", "0.0"))
        except (TypeError, ValueError):
            model_size = 0.0  # Fallback value

        return {
            "model_name": model_name,
            "size": model_size,
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

    def merge_with_defaults(self, prompt_defaults: dict, model_name: str) -> dict:
        """when loading a role-prompt with LLM, overrides the role-prompt hyperparameters with default LLM ones"""
        overrides = self.get_llm_params(model_name)
        return {**prompt_defaults, **overrides}

    def get_embeddings_list(self):
        """
        Returns the list of LLM names that capabilities contains 'embedding'.
        Optimized request to recover only the Model_Name column.
        """
        rows = (
            self.db.query(LLMProperties.model_name)
            .filter(LLMProperties.capabilities.contains(["embedding"]))
            .all()
        )
        return [r[0] for r in rows]
