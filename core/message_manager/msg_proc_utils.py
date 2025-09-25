def escape_braces(text: str, keep_placeholders: set[str] | None = None) -> str:
    """
    Double all braces except those that correspond to authorized placeholders.
    """
    if not text:
        return text

    # doubler toutes les accolades
    escaped = text.replace("{", "{{").replace("}", "}}")

    # remettre les placeholders permis à leur forme originale
    if keep_placeholders:
        for ph in keep_placeholders:
            escaped = escaped.replace(f"{{{{{ph}}}}}", f"{{{ph}}}")

    return escaped


def count_tokens_from_text(text: str, context_parser=None) -> int:
    """
    Delegate to `ContextParser` (or any other counter) ;
    We keep here the function pure so that the GUI part does not depend on a parser that uses QT.
    """
    # Le parser réel est injecté dans `UserMessageProcessor` via la dépendance,
    # mais on expose une fonction utilitaire pour les tests unitaires.
    if not context_parser:
        return 0
    return context_parser.count_tokens_from_text(text)
