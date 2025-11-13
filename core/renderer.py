# renderer.py   –   markdown -> html -> highlighted html -> QTextBrowser
import html as _html
import re

import markdown2
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name  # , guess_lexer
from pygments.style import Style  # , StyleMeta
from pygments.token import (
    Comment,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    Whitespace,
)
from pygments.util import ClassNotFound

from .render_templates import CSS_HTML_TEMPLATE, CSS_MD_TEMPLATE

# Monokai-style default colours
_DEFAULT_CODE_FG = "#f8f8f2"
_DEFAULT_CODE_BG = "#272822"


# Mapping digit -> circled-digit Unicode character
_CIRCLED_DIGITS = {
    "0": "\u24ea",  # ⓪
    "1": "\u2460",  # ①
    "2": "\u2461",  # ②
    "3": "\u2462",  # ③
    "4": "\u2463",  # ④
    "5": "\u2464",  # ⑤
    "6": "\u2465",  # ⑥
    "7": "\u2466",  # ⑦
    "8": "\u2467",  # ⑧
    "9": "\u2468",  # ⑨
    "10": "\u2469",  # ⑩
}


class MyVSLikeStyle(Style):
    default_style = ""  # Le style de base pour tout texte non spécifié
    styles = {
        # Texte de base et arrière-plan
        Text: "#59b8fd",  # Couleur par défaut du texte
        Whitespace: "",  # Rend les espaces invisibles (ou utilise `#888` pour les voir)
        # Mots-clés et types
        Keyword: "#eb9de4",  # Mots-clés génériques
        Keyword.Namespace: "#eb9de4",  # Mots-clés liés aux namespaces (import, from)
        Keyword.Constant: "italic #3479d5",  # None, True, False
        Keyword.Declaration: "#eb9de4",  # var, let, def, class
        Keyword.Reserved: "#3479d5",  # Mots-clés réservés
        Keyword.Type: "#56c9b0",  # Types built-in (int, str, char)
        # Ponctuation
        Punctuation: "bold #e6ce33",  # Ponctuation ([ ] { } ( ) ; : ,)
        # Opérateurs et structure
        Operator: "#ffffff",  # Opérateurs (+, -, *, /)
        Operator.Word: "italic #3479d5",  # in, not,
        # Noms et identifiants
        # Name: "#B8FE9C",  # Nom générique
        Name: "#9CDCFE",  # Nom générique
        Name.Attribute: "#FFD88A",  # Attributs (obj.attr)
        Name.Builtin: "#71c956",  # Fonctions/types built-in (len, str)
        Name.Builtin.Pseudo: "#a4d9fd",  # Self, cls, this
        Name.Class: "bold #56ab70",  # Noms de classes
        Name.Constant: "bold #3c6dad",
        Name.Decorator: "#97a5f3",  # Décorateurs (@staticmethod)
        Name.Entity: "bold #3c6dad",
        Name.Exception: "#56c9b0",
        Name.Function: "bold italic #DCDCAA",  # Noms de fonctions
        Name.Function.Magic: "#d9dba8",  # Méthodes magiques (__init__)
        Name.Property: "italic #FFD88A",
        Name.Label: "italic #9CDCFE",
        Name.Namespace: "bold #56c9b0",  # Noms de modules/paquets
        Name.Variable: "#1d626e",  # Variables
        Name.Variable.Global: "#65bcfd",  # Variables globales
        Name.Variable.Instance: "#9CFEFE",  # Variables d'instance
        Name.Variable.Magic: "#9CBEFE",  # Variables magiques (__doc__)
        # Littéraux
        String: "#CE9178",  # Chaînes de caractères
        String.Doc: "#CE9178",  # Docstrings
        String.Escape: "bold #E4C582",  # Séquences d'échappement (\n, \t)
        Number: "#df6e4b",
        Number.Integer: "#df6e4b",  # Entiers
        Number.Float: "#df6e4b",  # Flottants
        # Commentaires
        Comment: "italic #3C4E33",  # Commentaires standard
        Comment.Single: "italic #6A9955",  # Commentaires sur une ligne
        Comment.Multiline: "italic #6A9955",  # Commentaires multilignes
        Comment.Preproc: "italic #6A9955",  # Directives de préprocesseur
        # Tokens génériques (utiles pour les sorties)
        Generic.Output: "#444",  # Sortie de console
        Generic.Error: "#f44747",  # Messages d'erreur
        Generic.Heading: "bold #569CD6",  # En-têtes
        Generic.Subheading: "bold #4EC9B0",  # Sous-en-têtes
        Generic.Traceback: "#f44747",  # Tracebacks
    }


# compiler les regex en une fois...
_RE_SOFT_BREAK = re.compile(r"([^\n])\n(?!\n)")
_RE_KEYCAP = re.compile(r"(\d{1,2})\uFE0F?\u20E3")
_RE_CODEBLOCK = re.compile(
    r"""(?P<wrap><div[^>]*class=["'][^"']*codehilite[^"']*["'][^>]*>\s*)?  # optionnel wrapper
            <pre[^>]*>                                                     # <pre>
            (?:\s*<span[^>]*>\s*</span>)?                                  # optionnel empty span
            \s*<code(?P<attrs>[^>]*)>                                      # <code ...>
            (?P<code>.*?)                                                  # code body (.*? est pas greedy)
            </code>\s*</pre>                                               # </code></pre>
            (?(wrap)\s*</div>)                                             # close wrapper si present
        """,
    flags=re.DOTALL | re.IGNORECASE | re.VERBOSE,
)


class MarkdownRenderer:
    """
    Convert Markdown text into styled HTML
    (using regex/pygments for code and qss/current_theme for markdown).
    """

    # CSS template with placeholders
    CSS_TEMPLATE = """
    <style>
      h1 { color: /*Accent*/ ; font-size: 180% ; font-weight: bolder ; text-align: center;}
      h2 { color: /*Accent*/ ; font-size: 160% ; font-weight: bold ; }
      h3 { color: /*Text*/ ; font-size: 150% ; font-weight: bolder ; margin-left : 20px;}
      h4 { color: /*Text*/ ; font-size: 140% ; font-weight: bolder ; margin-left : 40px;}
      h5 { color: /*Text*/ ; font-size: 130% ; font-weight: bolder ; margin-left : 60px;}
      table { border: 2px solid /*Warning*/; border-collapse: collapse; width: auto;}
      table, th, td { border: 2px solid /*Warning*/; padding: 4px;}
      img { max-width: 1024px; max-height: 1024px; width: auto; height: auto; display: block; margin: 8px auto;}
    </style>
    """

    def __init__(self, theme_manager=None, code_style: str = "monokai"):
        self.theme_manager = theme_manager
        self.code_style = code_style
        # Cache formatter for performance
        self._formatter = HtmlFormatter(noclasses=True, style=MyVSLikeStyle, nowrap=True)

    # Soft-line-break handling
    def _add_soft_line_breaks(self, text: str) -> str:
        parts = re.split(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)", text)
        for i in range(0, len(parts), 2):  # seulement parties hors code
            parts[i] = _RE_SOFT_BREAK.sub(r"\1  \n", parts[i])
        return "".join(parts)

    # Highlight code blocks
    def _highlight_code_html(self, html: str, md_rend=True) -> str:
        """
        Replace <pre><code ...>...</code></pre> blocks with Pygments-highlighted HTML.
        """

        def repl(m):
            attrs = m.group("attrs")
            code_html = m.group("code")

            # pour toutes les balises errantes que Markdown2 peut avoir injecté à l'intérieur de <code>
            code_no_tags = code_html
            if "<" in code_html:
                code_no_tags = re.sub(r"<[^>]+>", "", code_html)
            code_text = _html.unescape(code_no_tags)

            # detection du language - avec priorité à Python pour les exemples de code
            lang = None
            for pattern in (
                r'class=["\'][^"\']*language-(?P<lang>[^ "\']+)["\']',
                r'class=["\'][^"\']*lang-(?P<lang>[^ "\']+)["\']',
                r'data-lang=["\'](?P<lang>[^"\']+)["\']',
            ):
                language_match = re.search(pattern, attrs, flags=re.IGNORECASE)
                if language_match:
                    lang = self._normalize_lang(language_match.group("lang"))
                    break

            # Si aucun langage n'est détecté, on essaie de deviner avec une heuristique
            if lang is None:
                # Heuristique: si le code contient des mots-clés Python, on force Python
                python_keywords = [
                    "class",
                    "def",
                    "import",
                    "from",
                    "return",
                    "if",
                    "else",
                    "for",
                    "while",
                ]
                if any(keyword in code_text for keyword in python_keywords):
                    lang = "python"
                # si le code commence par un commentaire Python
                elif code_text.strip().startswith("#"):
                    lang = "python"

            lexer = None
            if lang:
                # print("language en markdown blocks :", lang)
                try:
                    lexer = get_lexer_by_name(lang)
                except ClassNotFound:
                    try:
                        lexer = get_lexer_by_name(self._normalize_lang(lang))
                    except ClassNotFound:
                        lexer = None

            if lexer is None:
                try:
                    # print("guess lexer ON")
                    lexer = get_lexer_by_name("python")
                    # lexer = guess_lexer(code_text)
                except Exception:
                    # Fallback sur Python plutôt que text pour une meilleure coloration
                    print("fallback de guess lexer")
                    lexer = get_lexer_by_name("python")

            # Highlight with Pygments
            highlighted = highlight(code_text, lexer, self._formatter)

            # wrap les fragments mis en évidence en un seul <pre> en forcant bg/fg/font
            return (
                (
                    f'<table cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin: 15;">'
                    f'<tr><td style="background:{_DEFAULT_CODE_BG}; padding:10px; border-radius:6px; ">'
                    f'<pre style="margin:0; color:{_DEFAULT_CODE_FG}; tab-size:4; '
                    f'white-space: pre-wrap; word-wrap: break-word; display: inline-block;">'
                    f"{highlighted}"
                    f"</pre></td></tr></table>"
                )
                if md_rend
                else (
                    f'<table cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin: 15;">'
                    f'<tr><td style="background:{_DEFAULT_CODE_BG}; padding:0px;">'
                    f'<pre style="margin:0; color:{_DEFAULT_CODE_FG}; tab-size:4; '
                    f'white-space: pre-wrap; word-wrap: break-word; display: inline-block;">'
                    f"{highlighted}"
                    f"</pre></td></tr></table>"
                )
            )

        # Appliquer la substitution pour chaque bloc <pre><code>
        return _RE_CODEBLOCK.sub(repl, html)

    #  Emoji -> conversion des chiffres encerclés (gpt-oss les adore...)
    def _replace_keycap_emoji(self, text: str) -> str:
        # pattern = re.compile(r"(\d{1,2})\uFE0F?\u20E3")

        def _repl(match: re.Match) -> str:
            digit = match.group(1)
            return _CIRCLED_DIGITS.get(digit, digit)

        return _RE_KEYCAP.sub(_repl, text)

    def render(self, markdown_text: str, md_rend=True) -> str:
        # garder le thinking entre balises dans indications markdown
        markdown_text = re.sub(
            r"<think>(.*?)</think>", r"**[thinking]**\n\n\1\n\n**[/thinking]**", markdown_text, flags=re.S | re.I
        )

        # soft line breaks (outside fenced code)
        markdown_text = self._add_soft_line_breaks(markdown_text)

        # conversion des chiffres encerclés
        markdown_text = self._replace_keycap_emoji(markdown_text)

        # markdown -> html (keep fenced code blocks)
        html_body = markdown2.markdown(
            markdown_text,
            extras=[
                "tables",
                "fenced-code-blocks",
                "strike",
                "task_list",
                "spoiler",
                "cuddled-lists",
                "code-friendly",
            ],
        )

        # post-process: pygments highlight + couleurs
        html_body = self._highlight_code_html(html_body) if md_rend else self._highlight_code_html(html_body, md_rend=False)

        return html_body

    def themed_stylesheet(self) -> str:
        """Return the CSS with placeholders replaced by current theme colors."""
        return self.theme_manager.apply_theme_to_stylesheet(self.CSS_TEMPLATE)

    #  Language normalisation helper (unchanged)
    def _normalize_lang(self, lang: str) -> str:
        if not lang:
            return lang
        norm = lang.lower().strip()
        repl = {
            "bat": "batch",
            "c++": "cpp",
            "c#": "csharp",
            "c": "c",
            "cfg": "ini",
            "conf": "ini",
            "cpp": "cpp",
            "css": "css",
            "csv": "csv",
            "dart": "dart",
            "f#": "fsharp",
            "go": "go",
            "html": "html",
            "ini": "ini",
            "java": "java",
            "js": "javascript",
            "json": "json",
            "jsx": "jsx",
            "kt": "kotlin",
            "log": "text",
            "md": "markdown",
            "markdown": "markdown",
            "php": "php",
            "pl": "perl",
            "ps1": "powershell",
            "py": "python",
            "python": "python",
            "qss": "qss",
            "rb": "ruby",
            "rs": "rust",
            "scala": "scala",
            "sh": "bash",
            "sql": "sql",
            "swift": "swift",
            "txt": "text",
            "ts": "typescript",
            "tsx": "tsx",
            "xml": "xml",
            "yaml": "yaml",
            "yml": "yaml",
        }
        return repl.get(norm, norm)

    def session_to_markdown(self, session):
        """proccess the session messages to render them in an app-current-theme stylized markdown doc"""
        lines = [
            f"{self.theme_manager.apply_theme_to_stylesheet(CSS_MD_TEMPLATE)}\n"
            f"# AInter-Session :<br><font size='6'>**{session.session_name}**</font>"
        ]
        for m in session.messages:
            if m.sender == "user":
                meta = (
                    f"<br><br><font size='5'>**📜**</font><llm>🧙‍♂️{m.sender.capitalize()}"
                    f"<font size='3'><date> - {m.timestamp.strftime("%Y/%m/%d %H:%M")}"
                    "</date></font>"
                    "</llm><br><br>"
                )
            if m.sender == "llm":
                meta = (
                    f"<br><br><font size='5'>**📜**</font><llm>🤖"
                    f"<font size='6'>{m.llm_name} </font><font size='5'> *as* "
                    f"<role>{m.role_type} </role></span></font>"
                    f"<font size='3'><date> - {m.timestamp.strftime("%Y/%m/%d %H:%M")}"
                    "</date></font></llm><br><br>"
                )
            lines.append(f"{meta}\n{m.content.replace("\n", " \n").replace("file:///", "")}\n")  #
        return "\n\n".join(lines)

    def session_to_html(self, session):
        """proccess the session messages to render them in an app-current-theme stylized html doc"""
        themed_css_style = self.theme_manager.apply_theme_to_stylesheet(CSS_HTML_TEMPLATE)
        lines = [
            f"<html><head><meta charset='utf-8'>{themed_css_style}</head><body>",
            f"<h1>AInter-Session :<br>{session.session_name}</h1>",
        ]
        for m in session.messages:
            if m.sender == "user":
                meta = (
                    f"<br><br><llm>🧙‍♂️{m.sender.capitalize()}"
                    f"<font size='3'><date> - {m.timestamp.strftime("%Y/%m/%d %H:%M")}"
                    "</date></font>"
                    "</llm><br>"
                )
            if m.sender == "llm":
                meta = (
                    f"<br><br><llm>🤖"
                    f"<font size='6'>{m.llm_name} </font><font size='5'> <i>as</i> "
                    f"<role>{m.role_type} </role></span></font>"
                    f"<font size='3'><date> - {m.timestamp.strftime("%Y/%m/%d %H:%M")}"
                    "</date></font></llm><br>"
                )
            html_body = self.render(m.content)
            lines.append(f"<div><p>{meta}</p><br>{html_body}</div>")  #
        lines.append("</body></html>")
        return "\n".join(lines)
