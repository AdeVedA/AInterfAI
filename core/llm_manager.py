# -*- coding: utf-8 -*-
import subprocess
import threading
import time
from typing import Optional

import requests
from langchain_ollama.llms import OllamaLLM

from core.llm_properties import LLMPropertiesManager


class LLMManager:
    """
    Manages Ollama Large Language Models (LLMs) by handling
    server initialization, model pulling, and LLM instance creation.
    Attributes:
        ollama_host (str): The URL of the Ollama server.
        serve_cmd (list): Command to start the Ollama server if not running.
    """

    def __init__(self, ollama_host="http://localhost:11434", serve_cmd=None, session_manager=None):
        """
        Initializes the LLMManager with the specified Ollama server host and command.
        Args:
            ollama_host (str): The URL of the Ollama server (default: "http://localhost:11434").
            serve_cmd (list): Command to start the Ollama server if not running (default: ["ollama", "serve"]).
        """
        self.ollama_host = ollama_host
        self.serve_cmd = serve_cmd or ["ollama", "serve"]
        self._ensure_server_running()
        self.session_manager = session_manager
        self.props_mgr = LLMPropertiesManager(self.session_manager.db)
        self._keep_alive = 300

    @property
    def keep_alive(self):
        return self._keep_alive

    @keep_alive.setter
    def keep_alive(self, value):
        if self._keep_alive != value:
            self._keep_alive = value

    def _ensure_server_running(self):
        """
        Ensures the Ollama server is running by attempting to connect to it.
        If the server is not reachable, it starts the server using the provided command.
        """
        try:
            requests.get(self.ollama_host, timeout=1)
        except requests.exceptions.RequestException:
            subprocess.Popen(self.serve_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)

    def get_llm(self, model_name: str, params: dict) -> OllamaLLM:
        """
        Instancie un modèle OllamaLLM avec paramètres runtime (num_ctx, num_thread, etc.)
        directement via l'API REST, avec préchargement non-bloquant.
        """
        # TODO on verra plus tard si on permet de puller depuis le log
        available = [m["name"] for m in self.list_models()]
        if model_name not in available:
            print(f"Pulling model {model_name}...")
            self.pull_model(model_name)

        # 1. Construire les options pour l'API /api/generate
        ollama_api_opts = {
            k: v
            for k, v in {
                "temperature": params.get("temperature", 0.7),
                "top_k": params.get("top_k", 40),
                "repeat_penalty": params.get("repeat_penalty", 1.1),
                "top_p": params.get("top_p", 0.9),
                "min_p": params.get("min_p", 0.0),
                "num_ctx": params.get("default_max_tokens", 8192),
                "flash_attention": params.get("flash_attention", False),
                "kv_cache_type": params.get("kv_cache_type", "f16"),
                "use_mmap": params.get("use_mmap", True),
                "num_thread": params.get("num_thread", 8),
            }.items()
            if v is not None
        }
        # autres options API utiles pour l'avenir...
        # "stop": params.get("stop", None),
        # "seed": params.get("seed", None),
        # "num_keep": params.get("num_keep", None),
        # "num_predict": params.get("num_predict", None),
        # "typical_p": params.get("typical_p", None),
        # "repeat_last_n": params.get("repeat_last_n", None),
        # "presence_penalty": params.get("presence_penalty", None),
        # "frequency_penalty": params.get("frequency_penalty", None),
        # "penalize_newline": params.get("penalize_newline", None),
        # "numa": params.get("numa", None),
        # "num_batch": params.get("num_batch", None),
        # "num_gpu": params.get("num_gpu", None),
        # "main_gpu": params.get("main_gpu", None),
        # ollama_api_opts = {k: v for k, v in ollama_api_opts.items() if v is not None}

        print("API options:", ollama_api_opts)

        # 2. Préchargement non bloquant avec same API options
        def preload():
            try:
                resp = requests.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": "",
                        "options": ollama_api_opts,
                        "keep_alive": self.keep_alive,
                        "stream": False,
                    },
                    timeout=(8, 60),
                )
                resp.raise_for_status()
            except Exception as e:
                print(f"LLM preload error : {e}")

        threading.Thread(target=preload, daemon=True).start()

        # 3. Construire les kwargs pour OllamaLLM
        llm_kwargs = {
            "model": model_name,
            "reasoning": params.get("think", None),
            "temperature": params.get("temperature"),
            "top_k": params.get("top_k", 40),
            "top_p": params.get("top_p", 0.9),
            "repeat_penalty": params.get("repeat_penalty", 1.1),
            "min_p": params.get("min_p", 0.0),
            "num_ctx": params.get("default_max_tokens", 8192),
            "flash_attention": params.get("flash_attention", False),
            "kv_cache_type": params.get("kv_cache_type", "f16"),
            "use_mmap": params.get("use_mmap", True),
            "num_thread": params.get("num_thread"),
        }
        # # others
        # "stop": params.get("stop"),
        # "seed": params.get("seed"),

        print("LangChain LLM kwargs:", llm_kwargs)

        # Instanciation
        llm = OllamaLLM(**llm_kwargs)

        return llm

    def is_model_loaded(self, model_name: str) -> bool:
        """verifies if a model_name is in the ollama currently loaded models
        Args :
            model_name[str] : the name of the model to indicate 'loaded' state
        Returns :
            boolean : True if model loaded, else false
        """
        if not model_name:
            return False
        try:
            result = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=1.5)
            # Recherche d'une ligne contenant le nom modèle exact (peut adapter selon le format)
            for line in result.stdout.splitlines():
                if model_name.lower() in line.lower():
                    return True
            return False
        except Exception as e:
            print(f"Error in is_model_loaded: {e}")
            return False

    def unload_ollama_model(self, model_name: str):
        """unloads the model from Ollama (freeing VRAM/RAM)"""
        try:
            # print(f"### --- Unloading model ({model_name}).")
            subprocess.run(["ollama", "stop", model_name], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error when unloading the model : {e}")

    def list_models(self) -> list[str]:
        """
        Lists all available models on the Ollama server.
        Returns:
            list[str]: A list of model names.
        """
        # Synchronisation conditionnelle
        threading.Thread(target=self.props_mgr.sync, daemon=True).start()

        # Appel à l'API Ollama pour la liste
        self._ensure_server_running()
        resp = requests.get(f"{self.ollama_host}/api/tags")  # liste modèles locaux d'ollama
        resp.raise_for_status()
        data = resp.json()
        # print(data)
        models = data.get("models", [])
        # print(f"models : {models}")
        # Récupérer la liste des modèles embeddings depuis LLMPropertiesManager
        embeddings_names = set(self.props_mgr.get_embeddings_list())

        # Filtrer en enlevant les embeddings
        models[:] = [m for m in models if m.get("name") not in embeddings_names]
        return models

    def sort_llms_by_name(self, llm_list: list[dict[str, any]]) -> list[str]:
        """
        Sorts a list of LLM dictionaries by the 'name' key and returns a list of model names.
        Args:
            llm_list (list[Dict[str, Any]]): A list of dictionaries, each representing an LLM with a 'name' key.
        Returns:
            list[str]: A list of model names sorted alphabetically.
        """
        return sorted([llm["name"] for llm in llm_list])

    def pull_model(self, model_name: str):
        """
        Pulls a specific model from the Ollama server if it's not already present.
        Args:
            model_name (str): The name of the model to pull.
        """
        self._ensure_server_running()
        payload = {"model": model_name, "stream": False}
        resp = requests.post(f"{self.ollama_host}/api/pull", json=payload)
        resp.raise_for_status()

    def get_model_template(self, model_name: str) -> Optional[str]:
        """
        Recovers the model template for a specific model of the Olllama server.
        Args:
            model_name (str): The name of the model to retrieve the template for.
        Returns:
            Optional[str]: The prompt template if found, otherwise None.
        """
        try:
            response = requests.post(f"{self.ollama_host}/api/show", json={"model": model_name})
            response.raise_for_status()

            model_info = response.json()
            print("JSON Response for template request :", model_info)
            return model_info.get("template", None)

        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            return None
        except KeyError:
            print("Unexpected response format")
            return None
