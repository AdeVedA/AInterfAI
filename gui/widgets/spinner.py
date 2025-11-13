from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel


def create_spinner(
    text: str = "Processing...",
    frames: list[str] | None = None,
    interval: int = 120,
    object_name: str = "spinnerLabel",
    style: str = "color: gray; font-style: italic;",
) -> QLabel:
    """
    Create a pseudo-animated spinner QLabel with text.

    Args:
        text: Text displayed after the spinner symbol.
        frames: List of Unicode frames for the animation.
        interval: Delay (ms) between frame updates.
        object_name: For QSS styling.
        style: Inline stylesheet.

    Returns:
        QLabel with an attached .stop_spinner() method.
    """
    if frames is None:
        # spinner steps
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # mutable holder pour le message actuel
    msg = {"txt": text}

    lbl = QLabel(f"   {frames[0]} {msg['txt']}")
    lbl.setObjectName(object_name)
    if style:
        lbl.setStyleSheet(style)

    spinner_index = {"i": 0}  # mutable ref

    timer = QTimer(lbl)  # parent = lbl pour auto-clean

    def _update():
        spinner_index["i"] = (spinner_index["i"] + 1) % len(frames)
        lbl.setText(f"   {frames[spinner_index['i']]} {msg['txt']}")

    timer.timeout.connect(_update)
    timer.start(interval)

    # API pour changer le text affiché pendant que le spinner fonctionne
    def set_message(new_text: str) -> None:
        msg["txt"] = new_text

    lbl.setMessage = set_message

    # pour stopper l'animation
    def stop_spinner():
        # stop
        if timer.isActive():
            timer.stop()
        lbl.hide()
        # enlèver le widget du layout immédiatement
        try:
            parent = lbl.parentWidget()
            if parent is not None:
                lay = parent.layout()
                if lay is not None:
                    lay.removeWidget(lbl)
        except Exception:
            pass
        lbl.deleteLater()

    lbl.stop_spinner = stop_spinner  # méthode incluse attachée au QLabel

    return lbl
