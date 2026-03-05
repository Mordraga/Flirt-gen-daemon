import tkinter as tk

def _register_text_widget(self, widget: tk.Text) -> None:
    self._themed_text_widgets.append(widget)
    self._apply_text_widget_theme()

def _apply_text_widget_theme(self) -> None:
    for widget in list(self._themed_text_widgets):
        try:
            widget.configure(
                bg=self.theme_palette["field_bg"],
                fg=self.theme_palette["field_text"],
                insertbackground=self.theme_palette["field_text"],
            )
        except Exception:
            continue
    for canvas in list(self._tab_scroll_canvases):
        try:
            canvas.configure(background=self.theme_palette["surface"])
        except Exception:
            continue

def _set_text_widget_content(self, widget: tk.Text, text: str) -> None:
    widget.configure(state=tk.NORMAL)
    widget.delete("1.0", tk.END)
    widget.insert("1.0", text)
    widget.configure(state=tk.DISABLED)
