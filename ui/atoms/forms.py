def _bind_enter_to_quick_test(self, widget) -> None:
    widget.bind("<Return>", lambda _event: self._fire_quick_test())
    widget.bind("<KP_Enter>", lambda _event: self._fire_quick_test())
