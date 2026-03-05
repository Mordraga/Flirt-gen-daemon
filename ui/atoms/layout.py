import tkinter as tk
from tkinter import ttk

def _create_scrollable_tab_container(self, notebook: ttk.Notebook) -> tuple[ttk.Frame, ttk.Frame]:
    outer = ttk.Frame(notebook)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)

    canvas = tk.Canvas(
        outer,
        highlightthickness=0,
        borderwidth=0,
        background=self.theme_palette["surface"],
    )
    self._tab_scroll_canvases.append(canvas)
    scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")

    content = ttk.Frame(canvas)
    content.columnconfigure(0, weight=1)
    window_id = canvas.create_window((0, 0), window=content, anchor="nw")

    def _on_content_configure(_event=None):
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _on_canvas_configure(event):
        try:
            canvas.itemconfigure(window_id, width=event.width)
        except Exception:
            pass

    def _on_mouse_wheel(event):
        try:
            if event.delta != 0:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        except Exception:
            return None

    def _on_button4(_event):
        try:
            canvas.yview_scroll(-3, "units")
        except Exception:
            pass
        return "break"

    def _on_button5(_event):
        try:
            canvas.yview_scroll(3, "units")
        except Exception:
            pass
        return "break"

    content.bind("<Configure>", _on_content_configure)
    canvas.bind("<Configure>", _on_canvas_configure)
    for widget in (canvas, content):
        widget.bind("<MouseWheel>", _on_mouse_wheel, add="+")
        widget.bind("<Button-4>", _on_button4, add="+")
        widget.bind("<Button-5>", _on_button5, add="+")
    return outer, content

def _build_collapsible_section(
    self,
    parent: ttk.Frame,
    title: str,
    expanded: bool = True,
    state_key: str | None = None,
    fill: str = tk.X,
    expand: bool = False,
) -> tuple[ttk.LabelFrame, ttk.Frame]:
    expanded_state = expanded
    if state_key:
        stored = self.ui_state.get("collapsed_sections", {}).get(state_key)
        if isinstance(stored, bool):
            expanded_state = stored

    section = ttk.LabelFrame(parent, text=title)
    section.pack(fill=fill, expand=expand, padx=12, pady=8)
    section.columnconfigure(0, weight=1)

    header = ttk.Frame(section)
    header.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 0))
    header.columnconfigure(0, weight=1)

    toggle_text = tk.StringVar(value="Collapse" if expanded_state else "Expand")
    content = ttk.Frame(section)
    content.columnconfigure(1, weight=1)

    def _toggle():
        if content.winfo_ismapped():
            content.grid_remove()
            toggle_text.set("Expand")
            if state_key:
                self.ui_state.setdefault("collapsed_sections", {})[state_key] = False
                self._save_ui_state()
        else:
            content.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))
            toggle_text.set("Collapse")
            if state_key:
                self.ui_state.setdefault("collapsed_sections", {})[state_key] = True
                self._save_ui_state()
        self.root.after_idle(self._fit_window_to_active_tab)

    ttk.Button(header, textvariable=toggle_text, width=10, command=_toggle).grid(
        row=0, column=1, sticky="e", pady=2
    )

    if expanded_state:
        content.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))

    return section, content

def _scrolled_listbox(parent) -> tuple[tk.Listbox, ttk.Scrollbar]:
    """Return (listbox, scrollbar) packed into parent."""
    sb = ttk.Scrollbar(parent, orient=tk.VERTICAL)
    lb = tk.Listbox(
        parent,
        yscrollcommand=sb.set,
        selectmode=tk.SINGLE,
        width=60,
        font=("Segoe UI", 10),
        activestyle="none",
        borderwidth=0,
        highlightthickness=1,
        relief=tk.FLAT,
    )
    sb.config(command=lb.yview)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    return lb, sb

