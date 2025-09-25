from PyQt6.QtWidgets import QWidget


def add_separator(name, layout, thickness=7, top_space=4, bottom_space=7):
    """Add a separator with controlled spacing"""
    layout.addSpacing(top_space)

    name = QWidget()
    name.setFixedHeight(thickness)
    name.setObjectName("separator")
    layout.addWidget(name)

    layout.addSpacing(bottom_space)
