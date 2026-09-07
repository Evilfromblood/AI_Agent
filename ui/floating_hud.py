"""
Floating HUD Interface for JARVIS Desktop Assistant.
Built with CustomTkinter: frameless, dark-mode, top-centered command bar
with dynamic height expansion, status indicators, and quick action chips.
"""

import sys
import tkinter as tk
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

import customtkinter

if TYPE_CHECKING:
    from ui.app_controller import AppController


# Status theme configurations
STATUS_THEMES: Dict[str, Dict[str, str]] = {
    "IDLE": {
        "text": "● IDLE",
        "fg_color": "#1E293B",
        "text_color": "#94A3B8",
    },
    "LISTENING": {
        "text": "🎙 LISTENING",
        "fg_color": "#064E3B",
        "text_color": "#34D399",
    },
    "THINKING": {
        "text": "⚡ THINKING",
        "fg_color": "#78350F",
        "text_color": "#FBBF24",
    },
    "EXECUTING TOOL": {
        "text": "⚙ TOOL",
        "fg_color": "#312E81",
        "text_color": "#818CF8",
    },
    "SPEAKING": {
        "text": "🔊 SPEAKING",
        "fg_color": "#164E63",
        "text_color": "#22D3EE",
    },
    "ERROR": {
        "text": "⚠ ERROR",
        "fg_color": "#7F1D1D",
        "text_color": "#F87171",
    },
}


class JarvisFloatingHUD(customtkinter.CTk):
    """
    Spotlight-style floating desktop HUD.
    Operates as an always-on-top, frameless window centered at the upper portion
    of the display, expanding dynamically when displaying ReAct activity or answers.
    """

    def __init__(
        self,
        controller: Optional["AppController"] = None,
        width: int = 740,
        compact_height: int = 76,
        expanded_height: int = 380,
    ):
        super().__init__()

        self.controller = controller
        self.hud_width = width
        self.compact_height = compact_height
        self.expanded_height = expanded_height
        self.current_height = compact_height
        self.is_expanded = False
        self.is_visible = True

        # Drag state variables
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Configure CustomTkinter aesthetic
        customtkinter.set_appearance_mode("dark")
        customtkinter.set_default_color_theme("blue")

        self._configure_window()
        self._create_widgets()
        self._bind_events()

    def _configure_window(self) -> None:
        """Set frameless, topmost, and calculate centered screen placement."""
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)

        # Transparent background styling for Windows if supported
        self.configure(fg_color="#0F172A")

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        self.pos_x = (screen_width - self.hud_width) // 2
        self.pos_y = int(screen_height * 0.12)

        self.geometry(f"{self.hud_width}x{self.current_height}+{self.pos_x}+{self.pos_y}")

    def _create_widgets(self) -> None:
        """Instantiate HUD components."""
        # Main Outer Card Frame with subtle cyan accent border
        self.card_frame = customtkinter.CTkFrame(
            self,
            fg_color="#0B0F19",
            corner_radius=14,
            border_width=1.5,
            border_color="#0E7490",
        )
        self.card_frame.pack(fill="both", expand=True, padx=2, pady=2)

        # Top Bar: Drag header / command input / quick chips
        self.top_bar = customtkinter.CTkFrame(
            self.card_frame,
            fg_color="transparent",
            height=68,
        )
        self.top_bar.pack(fill="x", padx=10, pady=8)

        # 1. Status Pill Badge
        self.status_badge = customtkinter.CTkLabel(
            self.top_bar,
            text=STATUS_THEMES["IDLE"]["text"],
            fg_color=STATUS_THEMES["IDLE"]["fg_color"],
            text_color=STATUS_THEMES["IDLE"]["text_color"],
            corner_radius=10,
            font=("Segoe UI", 11, "bold"),
            width=84,
            height=28,
        )
        self.status_badge.pack(side="left", padx=(4, 8))

        # 2. Command Input Entry
        self.entry = customtkinter.CTkEntry(
            self.top_bar,
            placeholder_text="Ask JARVIS or speak... (Alt+Space toggle, Esc hide)",
            placeholder_text_color="#64748B",
            font=("Segoe UI", 13),
            fg_color="#1E293B",
            text_color="#F8FAFC",
            border_width=1,
            border_color="#334155",
            corner_radius=10,
            height=36,
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # 3. Quick Action Buttons (Mic, Vision, Telemetry, Hide)
        self.btn_mic = customtkinter.CTkButton(
            self.top_bar,
            text="🎙️ Voice",
            width=68,
            height=32,
            font=("Segoe UI", 11, "bold"),
            fg_color="#065F46",
            hover_color="#047857",
            text_color="#ECFDF5",
            corner_radius=8,
            command=self._on_mic_click,
        )
        self.btn_mic.pack(side="left", padx=2)

        self.btn_vision = customtkinter.CTkButton(
            self.top_bar,
            text="👁️ Vision",
            width=68,
            height=32,
            font=("Segoe UI", 11, "bold"),
            fg_color="#1E293B",
            hover_color="#334155",
            text_color="#38BDF8",
            corner_radius=8,
            command=self._on_vision_click,
        )
        self.btn_vision.pack(side="left", padx=2)

        self.btn_stats = customtkinter.CTkButton(
            self.top_bar,
            text="📊 Stats",
            width=64,
            height=32,
            font=("Segoe UI", 11, "bold"),
            fg_color="#1E293B",
            hover_color="#334155",
            text_color="#A78BFA",
            corner_radius=8,
            command=self._on_stats_click,
        )
        self.btn_stats.pack(side="left", padx=2)

        self.btn_close = customtkinter.CTkButton(
            self.top_bar,
            text="✕",
            width=32,
            height=32,
            font=("Segoe UI", 12, "bold"),
            fg_color="#1E293B",
            hover_color="#DC2626",
            text_color="#94A3B8",
            corner_radius=8,
            command=self.hide_window,
        )
        self.btn_close.pack(side="left", padx=(2, 4))

        # Activity / Thought / Answer Drawer (initially collapsed)
        self.activity_frame = customtkinter.CTkFrame(
            self.card_frame,
            fg_color="transparent",
        )

        # Monospaced Activity Textbox
        self.activity_box = customtkinter.CTkTextbox(
            self.activity_frame,
            font=("Consolas", 11),
            fg_color="#090D16",
            text_color="#CBD5E1",
            border_width=1,
            border_color="#1E293B",
            corner_radius=8,
            wrap="word",
        )
        self.activity_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _bind_events(self) -> None:
        """Bind keyboard and window interaction hooks."""
        # Enter key triggers query submission
        self.entry.bind("<Return>", lambda event: self._on_submit())
        # Escape key hides window
        self.bind("<Escape>", lambda event: self.hide_window())
        self.entry.bind("<Escape>", lambda event: self.hide_window())

        # Enable dragging the window by clicking on the top bar or card frame
        self.top_bar.bind("<Button-1>", self._start_drag)
        self.top_bar.bind("<B1-Motion>", self._do_drag)
        self.card_frame.bind("<Button-1>", self._start_drag)
        self.card_frame.bind("<B1-Motion>", self._do_drag)

    def _start_drag(self, event: tk.Event) -> None:
        """Record initial mouse pointer coordinates for window dragging."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _do_drag(self, event: tk.Event) -> None:
        """Update window position during mouse drag."""
        delta_x = event.x - self._drag_start_x
        delta_y = event.y - self._drag_start_y
        self.pos_x += delta_x
        self.pos_y += delta_y
        self.geometry(f"{self.hud_width}x{self.current_height}+{self.pos_x}+{self.pos_y}")

    def set_status(self, state: str, custom_text: Optional[str] = None) -> None:
        """Update the status badge indicator."""
        theme = STATUS_THEMES.get(state.upper(), STATUS_THEMES["IDLE"])
        display_text = custom_text or theme["text"]
        self.status_badge.configure(
            text=display_text,
            fg_color=theme["fg_color"],
            text_color=theme["text_color"],
        )

    def expand_window(self) -> None:
        """Expand the HUD downwards to show activity logs or agent responses."""
        if not self.is_expanded:
            self.activity_frame.pack(fill="both", expand=True)
            self.current_height = self.expanded_height
            self.geometry(f"{self.hud_width}x{self.current_height}+{self.pos_x}+{self.pos_y}")
            self.is_expanded = True

    def collapse_window(self) -> None:
        """Collapse the HUD back to compact single-row input mode."""
        if self.is_expanded:
            self.activity_frame.pack_forget()
            self.current_height = self.compact_height
            self.geometry(f"{self.hud_width}x{self.current_height}+{self.pos_x}+{self.pos_y}")
            self.is_expanded = False

    def append_activity(self, channel: str, message: str) -> None:
        """Append a ReAct log or observation to the activity feed."""
        self.expand_window()

        prefix_map = {
            "thought": "⚡ [Thought]: ",
            "plan": "📋 [Plan]: ",
            "critique": "🔍 [Critique]: ",
            "action": "⚙ [Action]: ",
            "action_input": "  ↳ Input: ",
            "observation": "👁 [Observation]: ",
            "final_answer": "🤖 [JARVIS]: ",
            "error": "❌ [Error]: ",
            "info": "💡 [Info]: ",
        }

        prefix = prefix_map.get(channel.lower(), f"[{channel.upper()}]: ")
        formatted_entry = f"{prefix}{message}\n"

        self.activity_box.configure(state="normal")
        self.activity_box.insert("end", formatted_entry)
        self.activity_box.see("end")
        self.activity_box.configure(state="disabled")

    def display_response(self, response: str) -> None:
        """Render final assistant response cleanly into the feed."""
        self.expand_window()
        self.activity_box.configure(state="normal")
        self.activity_box.insert("end", f"\n🤖 [JARVIS]: {response}\n\n")
        self.activity_box.see("end")
        self.activity_box.configure(state="disabled")

    def clear_activity(self) -> None:
        """Clear all text in the activity box and collapse the window."""
        self.activity_box.configure(state="normal")
        self.activity_box.delete("1.0", "end")
        self.activity_box.configure(state="disabled")
        self.collapse_window()

    def show_window(self) -> None:
        """Bring window to foreground and focus command entry."""
        self.deiconify()
        self.lift()
        self.wm_attributes("-topmost", True)
        self.focus_force()
        self.entry.focus_set()
        self.is_visible = True

    def hide_window(self) -> None:
        """Conceal the window into the background tray without stopping."""
        self.withdraw()
        self.is_visible = False

    def toggle_window(self) -> None:
        """Toggle between visible and concealed states."""
        if self.is_visible:
            self.hide_window()
        else:
            self.show_window()

    # Button click and user submission dispatchers
    def _on_submit(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        if self.controller:
            self.controller.handle_user_query(text)

    def _on_mic_click(self) -> None:
        if self.controller:
            self.controller.trigger_voice()

    def _on_vision_click(self) -> None:
        if self.controller:
            self.controller.trigger_screen_vision()

    def _on_stats_click(self) -> None:
        if self.controller:
            self.controller.trigger_system_stats()
