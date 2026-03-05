import tkinter as tk
from tkinter import ttk

def _clear_treeview(self, tree: ttk.Treeview | None) -> None:
    if tree is None:
        return
    for item in tree.get_children():
        tree.delete(item)
