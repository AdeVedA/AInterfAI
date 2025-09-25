"""
Themes manager for the Pyqt6 application
Responsible for the application of styles and the management of pallets
"""

import importlib
import json
import sys
from pathlib import Path

from .color_palettes import COLOR_PALETTES

GUI_CONFIG_PATH = Path(__file__).parent.parent.parent / "gui/gui_config.json"


def get_current_theme() -> str:
    """Recovers the active theme from the config file"""
    global CURRENT_THEME
    try:
        if GUI_CONFIG_PATH.exists():
            with open(GUI_CONFIG_PATH, "r") as f:
                config = json.load(f)
                CURRENT_THEME = config.get("theme", "Anthracite Carrot")
    except Exception as e:
        print(f"Erreur lecture config : {str(e)}")
    return CURRENT_THEME


def set_current_theme(theme_name: str):
    """Updates the active theme overall"""
    global CURRENT_THEME
    CURRENT_THEME = theme_name


class ThemeManager:
    """
    Application visual themes management class

    Attributes:
        app (QApplication): QT application instance
        current_theme (str): Name of the theme currently applied
    """

    def __init__(self, app=None):
        self.app = app
        self.current_theme = None

    def get_available_themes(self) -> list:
        """Return the list of themes available"""
        return list(COLOR_PALETTES.keys())

    def apply_theme(self, theme_name: str):
        """
        Apply a theme to the entire application
        """
        global CURRENT_THEME
        CURRENT_THEME = theme_name
        if theme_name not in COLOR_PALETTES:
            raise ValueError(f"Thème '{theme_name}' introuvable")

        palette = COLOR_PALETTES[theme_name]
        self.current_theme = theme_name

        # Charger le template CSS
        css_path = Path(__file__).parent / "themes.qss"
        css = css_path.read_text(encoding="utf-8")

        # Préparer mapping/substitutions
        substitutions = {
            "/*Base*/": palette["Base"],
            "/*Base1*/": palette["Base1"],
            "/*Text*/": palette["Text"],
            "/*Text1*/": palette["Text1"],
            "/*Text2*/": palette["Text2"],
            "/*Accent*/": palette["Accent"],
            "/*Danger*/": palette["Danger"],
            "/*Warning*/": palette["Warning"],
        }

        # Remplacer toutes les occurrences
        for placeholder, value in substitutions.items():
            css = css.replace(placeholder, value)

        # Appliquer les styles
        self.app.setStyleSheet(css)

    def get_color(self, color_role: str) -> str:
        """
        Returns a specific color of the current theme

        Args:
            color_role (str): Color role (ex: 'Base', 'Text')

        Returns:
            str: RGB value of color
        """
        return COLOR_PALETTES[self.current_theme][color_role]

    def reload_color_palettes(self):
        """
        Dynamically recharge the color pallets from the Color_Palettes.py file
        Useful to apply changes without restarting the application.
        """
        module_name = "core.theme.color_palettes"
        if module_name in sys.modules:
            module = sys.modules[module_name]
            importlib.reload(module)
        else:
            module = __import__(module_name, fromlist=["COLOR_PALETTES"])

        # Mettre à jour COLOR_PALETTES utilisé par ThemeManager
        global COLOR_PALETTES
        COLOR_PALETTES = module.COLOR_PALETTES

        # print("COLOR_PALETTES rechargé et mis à jour avec succès.")

    def apply_theme_to_stylesheet(self, stylesheet: str) -> str:
        """
        Replace placeholders (/*Base*/, /*Text*/, etc.) with the active theme colors.
        """
        palette = COLOR_PALETTES[self.current_theme]
        for key, value in palette.items():
            placeholder = f"/*{key}*/"
            stylesheet = stylesheet.replace(placeholder, value)
        return stylesheet
