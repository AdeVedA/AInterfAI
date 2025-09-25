import psutil
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .widgets.small_widgets import add_separator


# ConfigPanel : System prompt, paramètres LLM, read & update config
class ConfigPanel(QWidget):
    """
    Config Panel: Configuration of LLM settings and system prompt edition.
    """

    save_config = pyqtSignal()
    load_config = pyqtSignal()

    def __init__(self, parent=None, session_manager=None):
        super().__init__(parent)
        self.session_manager = session_manager

        layout = QVBoxLayout(self)
        self.setObjectName("config_panel")
        self.setMinimumWidth(180)
        self.setMaximumWidth(360)
        self.setContentsMargins(0, 0, 0, 0)
        # Titre
        # title = QLabel("Config")
        # title.setObjectName("titles")
        # layout.addWidget(title)
        self.sys_prmpt_label = QLabel("System Prompt :")
        sys_prmpt_tooltip = (
            "A system prompt sets the AI's behavior, rules, and context for a conversation.\n"
            "It guides responses by defining role, tone, and constraints.\n"
            "Users can adjust it to customize the chat interaction style, thus the 'LLM role'."
        )
        self.sys_prmpt_label.setObjectName("sys_prt_lbl")
        self.sys_prmpt_label.setToolTip(sys_prmpt_tooltip)
        layout.addWidget(self.sys_prmpt_label)
        self.system_prompt = QTextEdit(self)
        self.system_prompt.setObjectName("config_system_prompt")
        self.system_prompt.setToolTip(sys_prmpt_tooltip)
        self.system_prompt.setPlaceholderText("Edit the System Prompt for the selected Config...")
        layout.addWidget(self.system_prompt)

        # Helper to add slider with label and value
        def add_slider(name: str, minimum: int, maximum: int, default: int, scale: float, tooltip: str = None):
            row = QHBoxLayout()
            label = QLabel(name)
            label.setProperty("qssClass", "slider-title")
            row.addWidget(label)
            slider = DefaultMarkerSlider(Qt.Orientation.Horizontal, self)
            slider.setRange(minimum, maximum)
            slider.setValue(default)
            slider._scale = scale
            row.addWidget(slider)
            scale_condition = name in ["Temperature :", "Repeat Penalty :", "Top P :", "Min P :"]
            value_lbl = QLabel(f"{default/scale:.2f}" if scale_condition else f"{default/int(scale):.0f}")
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_lbl.setProperty("qssClass", "slider-value")
            row.addWidget(value_lbl)
            slider.valueChanged.connect(
                lambda v: value_lbl.setText(f"{v/scale:.2f}" if scale_condition else f"{v/int(scale):.0f}")
            )
            # Apply tooltip to all widgets if provided
            if tooltip:
                label.setToolTip(tooltip)
                slider.setToolTip(tooltip)
                value_lbl.setToolTip(tooltip)
            layout.addLayout(row)
            return slider

        self.temperature = add_slider(
            "Temperature :",
            0,
            200,
            50,
            100.0,
            tooltip="Temp ≈ 0 ↔ Ultra-deterministic (predictable, most likely response, minimum randomness)"
            "\nTemp ≈ 1 ↔ average randomness & creativity"
            "\nTemp > 1 ↔ more variations, randomness & creativity, complex thinking with unusual approach"
            "\n\nMany models have their own sweet temperature spot/range...",
        )
        self.temperature.setObjectName("config_slider_temp")

        self.top_k_slider = add_slider(
            "Top K :",
            0,
            100,
            40,
            1.0,
            tooltip="K threshold selects K most probable next-tokens from the set of probable ones.\n"
            "-> limits the number of considered possibilities for determining the most probable next-tokens. "
            "\n(default 50)\nTemperature a-like parameter.",
        )
        self.top_k_slider.setObjectName("config_slider_topk")

        self.repeat_penalty = add_slider(
            "Repeat Penalty :",
            0,
            200,
            110,
            100.0,
            tooltip="the higher the value, the most LLM will try to avoid repeating a recently generated token"
            "\n(default 1 <=> inactive parameter)",
        )
        self.repeat_penalty.setObjectName("config_slider_repeat")

        self.top_p = add_slider(
            "Top P :",
            0,
            100,
            95,
            100.0,
            tooltip="P threshold (cumulative probability) :\n"
            "makes a dynamic selection of the most likely next-tokens, ensuring their combined probabilities values "
            "never reaches or exceeds P.\n"
            "-> limits the number of the tokens being considered\n(default 0.95, can be lowered to be more "
            "deterministic)\nwhen adjusted wisely, top_k isn't really needed to adjust"
            "\nTemperature a-like parameter.",
        )
        self.top_p.setObjectName("config_slider_topp")

        self.min_p = add_slider(
            "Min P :",
            0,
            100,
            5,
            100.0,
            tooltip="min_p sets a filter to include only tokens whose probability is over this value.\n"
            "A higher min_p will exclude more unusual tokens",
        )
        self.min_p.setObjectName("config_slider_minp")

        self.max_tokens = add_slider(
            "Max tokens :",
            512,
            128000,
            4096,
            1,
            tooltip="the value of the context window which is the maximum number of tokens\n"
            "a LLM will accept as context (system prompt + user prompt + session history...)",
        )
        self.max_tokens.setObjectName("config_maxtokens")
        self.max_tokens.setSingleStep(512)  # incréments de 512 pour flèche haut/bas
        self.max_tokens.setPageStep(1024)  # incréments pour PageUp/PageDown

        # 1) Flash Attention
        flash_layout = QHBoxLayout()
        flash_tooltip = "Activate optimized attention in memory (FLASH_ATTENTION)"
        flash_title = QLabel("Flash Attention : ")
        flash_title.setToolTip(flash_tooltip)
        flash_title.setObjectName("lbl_flash_attent")
        flash_title.setProperty("qssClass", "slider-title")
        self.flash_attention = QCheckBox()
        self.flash_attention.setObjectName("config_flash_attent")
        self.flash_attention.setToolTip(flash_tooltip)
        flash_layout.addWidget(flash_title, alignment=Qt.AlignmentFlag.AlignLeft)
        flash_layout.addWidget(self.flash_attention, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(flash_layout)

        # 2) KV-Cache Type
        lbl_kv = QLabel("KV Cache Type : ")
        kv_tooltip = (
            "KV-Cache compression type (KV_CACHE_TYPE)\n"
            "f16 is uncompressed (best quality, recommanded for coding and precision tasks)"
        )
        lbl_kv.setProperty("qssClass", "slider-title")
        lbl_kv.setToolTip(kv_tooltip)
        self.kv_cache = QComboBox(self)
        self.kv_cache.setObjectName("config_KV_Cache")
        for mode in ("f16", "q8_0", "q4_0"):
            self.kv_cache.addItem(mode)
        # Aligner les items dans le menu
        for i in range(self.kv_cache.count()):
            self.kv_cache.setItemData(i, Qt.AlignmentFlag.AlignRight, Qt.ItemDataRole.TextAlignmentRole)
        self.kv_cache.setToolTip(kv_tooltip)
        self.kv_cache.setProperty("qssClass", "slider-value")
        self.kv_cache.setStyleSheet("QComboBox { text-align: right; padding-right: 2px; }")
        h_kv = QHBoxLayout()
        h_kv.addWidget(lbl_kv, alignment=Qt.AlignmentFlag.AlignLeft)
        h_kv.addWidget(self.kv_cache, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(h_kv)

        # 3) Thinking toggle (caché par defaut)
        thinking_layout = QHBoxLayout()
        thinking_tooltip = "If the model supports 'thinking', toggles whether to use it."
        self.thinking_label = QLabel("Enable Thinking:")
        self.thinking_label.setToolTip(thinking_tooltip)
        self.thinking_label.setProperty("qssClass", "slider-title")
        self.thinking = QCheckBox()
        self.thinking.setObjectName("config_thinking")
        self.thinking.setToolTip(thinking_tooltip)
        thinking_layout.addWidget(self.thinking_label, alignment=Qt.AlignmentFlag.AlignLeft)
        thinking_layout.addWidget(self.thinking, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(thinking_layout)
        # hide until we know model supports it
        self.thinking_label.hide()
        self.thinking.hide()

        layout.addSpacing(8)

        add_separator(name="line", layout=layout, thickness=5, top_space=5, bottom_space=5)

        # 4) mmap
        mmap_layout = QHBoxLayout()
        mmap_tooltip = (
            "Model load time improved when ON, but disable it if the model is larger than your available RAM"
        )
        mmap_title = QLabel("Use mmap : ")
        mmap_title.setToolTip(mmap_tooltip)
        mmap_title.setProperty("qssClass", "slider-title")
        self.mmap = QCheckBox()
        self.mmap.setObjectName("config_mmap")
        self.mmap.setToolTip(mmap_tooltip)
        mmap_layout.addWidget(mmap_title, alignment=Qt.AlignmentFlag.AlignLeft)
        mmap_layout.addWidget(self.mmap, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(mmap_layout)

        # 5) max_threads
        # calcul le nombre de coeurs réels disponibles sur le system
        cpuCount = psutil.cpu_count(logical=False)
        cpu_headroom = 2 if cpuCount >= 8 else 1
        self.num_threads = add_slider(
            "num_threads :",
            1,
            cpuCount,
            cpuCount - cpu_headroom,
            1.0,
            tooltip="Number of CPU cores for Ollama to use when inferencing\n"
            "Keeping some headroom (1 or 2 cores) is a good practice",
        )
        self.num_threads.setObjectName("config_num_threads")

        # 6) Save/Load buttons
        btn_layout = QHBoxLayout()
        self.btn_load = QPushButton("Load Config", self)
        self.btn_load.setObjectName("config_btn_load")
        self.btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load.setToolTip("loads the saved/default config for the duo 'Prompt Type/LLM'")
        self.btn_save = QPushButton("Save Config", self)
        self.btn_save.setObjectName("config_btn_save")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setToolTip("Saves the current config for the duo 'Prompt Type/LLM'")
        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        self.btn_load.clicked.connect(self.load_config)
        self.btn_save.clicked.connect(self.save_config)
        layout.addStretch()

    def get_parameters(self) -> dict:
        """
        Retrieve current PromptConfig fields:
        - description (system prompt)
        - LLM hyperparameters
        - max_tokens (context window)
        - flash attention, kv_cache_type, mmap, num_threads
        - "think" if supported by the model
        """
        params = {
            "description": self.system_prompt.toPlainText(),
            "temperature": self.temperature.value() / 100.0,
            "top_k": self.top_k_slider.value(),
            "repeat_penalty": self.repeat_penalty.value() / 100.0,
            "top_p": self.top_p.value() / 100.0,
            "min_p": self.min_p.value() / 100.0,
            "default_max_tokens": self.max_tokens.value(),
            "flash_attention": self.flash_attention.isChecked(),
            "kv_cache_type": self.kv_cache.currentText(),
            "use_mmap": self.mmap.isChecked(),
            "num_thread": self.num_threads.value(),
        }
        # ajoute le paramètre "thinking" s'il est visible (supporté par le modèle)
        if self.thinking.isVisible():
            params["think"] = self.thinking.isChecked()
        return params

    def set_model_defaults(self, model_name: str):
        """
        For each slider, If llmproperties has a factory value, it is displayed in red.
        If no props (property value is None), hides the markers in DefaultMarkerSlider.set_default.
        """
        from core.models import LLMProperties

        # Récupère via le session_manager injecté
        if not model_name or not self.session_manager:
            props = None
        else:
            # Charger proprement sans warning
            props = self.session_manager.db.query(LLMProperties).filter_by(model_name=model_name).first()
            print(props)

        # Pour chaque paramètre, on passe la valeur "affichée" et
        # le slider interne convertira en unités via _scale.
        self.temperature.set_default(getattr(props, "temperature", None) if props else None)
        self.top_k_slider.set_default(getattr(props, "top_k", None) if props else None)
        self.repeat_penalty.set_default(getattr(props, "repetition_penalty", None) if props else None)
        self.top_p.set_default(getattr(props, "top_p", None) if props else None)
        self.min_p.set_default(getattr(props, "min_p", None) if props else None)

        # Ajuste max_tokens
        if props and props.context_length:
            self.max_tokens.setMaximum(props.context_length)

        # Affiche ou cache le paramètre booléen "Thinking" selon les capacités du modèle
        supports_thinking = (
            props and isinstance(props.capabilities, (list, tuple)) and "thinking" in props.capabilities
        )
        # print(f"Thinking : -- {supports_thinking} -- for {model_name}")
        if supports_thinking is not None:
            self.thinking_label.setVisible(supports_thinking)
            self.thinking.setVisible(supports_thinking)
        else:
            self.thinking.setChecked(False)

        if not supports_thinking:
            self.thinking.setChecked(False)


class DefaultMarkerSlider(QSlider):
    """
    Horizontal QSlider which, in addition to the classic mobile handle for setting a parameter,
    displays a fixed vertical marker for the value of the "factory" parameter recovered by the Ollama API on the model.
    """

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._default = None

        # Le marqueur : un thin QFrame vertical, coloré en rouge via QSS
        self.marker = QFrame(self)
        self.marker.setObjectName("defaultMarker")
        self.marker.setFrameShape(QFrame.Shape.VLine)
        # self.marker.setFrameShadow(QFrame.Shadow.Plain)
        self.marker.setFixedWidth(6)
        self.marker.hide()

    def set_default(self, value: float | None):
        """Positions or masks the marker."""
        self._default = value
        if value is None:
            self._default = None
            self.marker.hide()
            return
        # Si on a un scale, appliquer : transform float->slider-units
        # Convertit la valeur utilisateur en unités de slider via _scale
        self._default = value * self._scale
        self.marker.setToolTip(f"Recommanded value : {value}")
        self.marker.show()
        self.update_marker()

    def resizeEvent(self, ev):
        """Overrides resizeEvent to update markers' positions in ConfigPanel with update_marker()"""
        super().resizeEvent(ev)
        QTimer.singleShot(0, self.update_marker)

    def update_marker(self):
        """sets the position of the default marker slider depending of its value and the slider size"""
        if self._default is None:
            return
        # Position logique du marker dans la plage
        min_val, max_val = self.minimum(), self.maximum()
        if max_val <= min_val:
            return

        ratio = (self._default - min_val) / (max_val - min_val)

        # Obtenir la taille du "handle" pour compenser le décalage
        style = self.style()
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)

        handle_width = style.pixelMetric(QStyle.PixelMetric.PM_SliderLength, opt, self)

        groove_width = self.width() - handle_width
        x = int(ratio * groove_width + handle_width / 2)

        # Applique la position horizontale corrigée
        self.marker.move(x - self.marker.width() // 2, 0)
        self.marker.setFixedHeight(self.height())
