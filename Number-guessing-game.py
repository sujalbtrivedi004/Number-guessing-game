"""Number Guessing Game - pure Python (Tkinter + SQLite).

No pip install needed. Just run this file in PyCharm.
- Tkinter  : window, responsive layout, custom flat styling
- sqlite3  : stores every game, every guess, and the leaderboard
"""
import os
import random
import sqlite3
import tkinter as tk
from datetime import datetime, timezone

# Sharper text on Windows high-DPI screens (safe to ignore elsewhere)
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guessing_game.db")

LEVELS = {
    "Easy":   {"max": 50,  "attempts": 10, "mult": 1},
    "Medium": {"max": 100, "attempts": 7,  "mult": 2},
    "Hard":   {"max": 500, "attempts": 9,  "mult": 3},
}

# ---- design tokens ----
PAPER, CARD, INK, MUTED, LINE = "#eef1f6", "#ffffff", "#1a2233", "#5d6882", "#d9dfeb"
ACCENT, ACCENT_HOVER, ACCENT_SOFT = "#2748ff", "#1c37c7", "#e6ebff"
HIGH, LOW, WIN, LOSE = "#e8590c", "#1c7ed6", "#2b8a3e", "#c92a2a"
FONT = "Segoe UI"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player       TEXT NOT NULL,
    difficulty   TEXT NOT NULL,
    max_number   INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    secret       INTEGER NOT NULL,
    low          INTEGER NOT NULL,
    high         INTEGER NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'playing',   -- playing | won | lost
    score        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guesses (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    value   INTEGER NOT NULL,
    result  TEXT NOT NULL                           -- low | high | correct
);
"""


# =====================  DATABASE LAYER  =====================
class Database:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def new_game(self, player, level):
        cfg = LEVELS[level]
        cur = self.conn.execute(
            """INSERT INTO games (player, difficulty, max_number, max_attempts, secret, low, high, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (player, level, cfg["max"], cfg["attempts"], random.randint(1, cfg["max"]),
             cfg["max"], datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()
        return self.get_game(cur.lastrowid)

    def get_game(self, game_id):
        return self.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()

    def make_guess(self, game_id, value):
        g = self.get_game(game_id)
        attempts = g["attempts"] + 1
        low, high, status, score = g["low"], g["high"], "playing", 0

        if value == g["secret"]:
            result, status = "correct", "won"
            left = g["max_attempts"] - attempts + 1
            score = round(100 * left / g["max_attempts"]) * LEVELS[g["difficulty"]]["mult"]
        elif value < g["secret"]:
            result, low = "low", max(low, value + 1)
        else:
            result, high = "high", min(high, value - 1)

        if status == "playing" and attempts >= g["max_attempts"]:
            status = "lost"

        self.conn.execute("INSERT INTO guesses (game_id, value, result) VALUES (?, ?, ?)",
                          (game_id, value, result))
        self.conn.execute("UPDATE games SET attempts=?, low=?, high=?, status=?, score=? WHERE id=?",
                          (attempts, low, high, status, score, game_id))
        self.conn.commit()
        return result, self.get_game(game_id)

    def top_scores(self, limit=5):
        return self.conn.execute(
            """SELECT player, difficulty, attempts, score FROM games WHERE status = 'won'
               ORDER BY score DESC, attempts ASC, id ASC LIMIT ?""", (limit,)).fetchall()

    def stats(self):
        r = self.conn.execute(
            "SELECT COUNT(*) AS played, COALESCE(SUM(status='won'), 0) AS won "
            "FROM games WHERE status != 'playing'").fetchone()
        return r["played"], r["won"]


# =====================  UI HELPERS  =====================
def make_button(parent, text, command, primary=True):
    bg, fg = (ACCENT, "white") if primary else (CARD, INK)
    hover = ACCENT_HOVER if primary else PAPER
    b = tk.Button(parent, text=text, command=command, font=(FONT, 11, "bold"), bg=bg, fg=fg,
                  activebackground=hover, activeforeground=fg, relief="flat", bd=0,
                  padx=18, pady=8, cursor="hand2", highlightthickness=0 if primary else 1,
                  highlightbackground=LINE)
    b.bind("<Enter>", lambda e: b["state"] == "normal" and b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


def make_entry(parent, **kw):
    return tk.Entry(parent, font=(FONT, 13), bg=PAPER, fg=INK, relief="flat", insertbackground=INK,
                    highlightthickness=2, highlightbackground=LINE, highlightcolor=ACCENT, **kw)


def label(parent, text="", size=11, weight="normal", fg=INK, **kw):
    return tk.Label(parent, text=text, font=(FONT, size, weight), bg=parent["bg"], fg=fg, **kw)


# =====================  APPLICATION  =====================
class App(tk.Tk):
    BREAKPOINT = 720   # below this width the leaderboard moves under the game

    def __init__(self):
        super().__init__()
        self.title("Narrow It Down - Number Guessing Game")
        self.geometry("980x680")
        self.minsize(360, 640)
        self.configure(bg=PAPER)

        self.db = Database()
        self.level = "Medium"
        self.game = None
        self.guess_list = []
        self.shown = (1.0, 100.0)
        self.anim_id = None
        self.wide = True

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.build_header()
        self.build_body()
        self.select_level("Medium")
        self.arrange()
        self.refresh_board()

        self.bind("<Configure>", self.on_resize)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- layout ----------
    def build_header(self):
        head = tk.Frame(self, bg=PAPER)
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 0))
        label(head, "Narrow it down", 28, "bold").pack(anchor="w")
        self.subtitle = label(head, "The computer picked a secret number. Each guess tells you higher or "
                              "lower, and the blue bar shows what's still possible.",
                              10, fg=MUTED, justify="left", wraplength=600)
        self.subtitle.pack(anchor="w")

    def build_body(self):
        self.body = tk.Frame(self, bg=PAPER)
        self.body.grid(row=1, column=0, sticky="nsew", padx=24, pady=20)

        self.game_card = tk.Frame(self.body, bg=CARD, highlightbackground=LINE, highlightthickness=1,
                                  padx=24, pady=22)
        self.board_card = tk.Frame(self.body, bg=CARD, highlightbackground=LINE, highlightthickness=1,
                                   padx=24, pady=22)
        self.game_card.columnconfigure(0, weight=1)

        self.setup_frame = self.build_setup(self.game_card)
        self.play_frame = self.build_play(self.game_card)
        self.setup_frame.grid(row=0, column=0, sticky="new")
        self.play_frame.grid(row=0, column=0, sticky="new")
        self.play_frame.grid_remove()

        label(self.board_card, "Top scores", 13, "bold").pack(anchor="w", pady=(0, 8))
        self.board_rows = tk.Frame(self.board_card, bg=CARD)
        self.board_rows.pack(fill="x")
        self.stats_label = label(self.board_card, "", 9, fg=MUTED)
        self.stats_label.pack(anchor="w", pady=(10, 0))

    def arrange(self):
        """Responsive switch: side by side on wide windows, stacked on narrow ones."""
        b = self.body
        if self.wide:
            self.game_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            self.board_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=0)
            b.columnconfigure(0, weight=3); b.columnconfigure(1, weight=2)
            b.rowconfigure(0, weight=1);    b.rowconfigure(1, weight=0)
        else:
            self.game_card.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 10))
            self.board_card.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
            b.columnconfigure(0, weight=1); b.columnconfigure(1, weight=0)
            b.rowconfigure(0, weight=1);    b.rowconfigure(1, weight=0)

    def on_resize(self, event):
        if event.widget is not self:
            return
        self.subtitle.config(wraplength=max(240, event.width - 48))
        wide = event.width >= self.BREAKPOINT
        if wide != self.wide:
            self.wide = wide
            self.arrange()
            self.refresh_board()

    # ---------- setup screen ----------
    def build_setup(self, parent):
        f = tk.Frame(parent, bg=CARD)
        label(f, "Start a game", 14, "bold").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        label(f, "Your name", 9, fg=MUTED).grid(row=1, column=0, columnspan=3, sticky="w")
        self.name_var = tk.StringVar()
        make_entry(f, textvariable=self.name_var).grid(row=2, column=0, columnspan=3, sticky="ew",
                                                       ipady=5, pady=(4, 16))
        label(f, "Difficulty", 9, fg=MUTED).grid(row=3, column=0, columnspan=3, sticky="w")

        self.level_buttons = {}
        for i, (name, cfg) in enumerate(LEVELS.items()):
            btn = tk.Button(f, text=f"{name}\n1 to {cfg['max']}, {cfg['attempts']} tries",
                            font=(FONT, 10), justify="left", anchor="w", relief="flat", bd=0,
                            padx=10, pady=8, cursor="hand2", fg=INK, highlightthickness=2,
                            command=lambda n=name: self.select_level(n))
            btn.grid(row=4, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0), pady=(4, 0))
            f.columnconfigure(i, weight=1, uniform="levels")
            self.level_buttons[name] = btn

        make_button(f, "Start game", self.start_game).grid(row=5, column=0, columnspan=3,
                                                          sticky="w", pady=(22, 0))
        return f

    def select_level(self, name):
        self.level = name
        for n, btn in self.level_buttons.items():
            on = n == name
            btn.config(bg=ACCENT_SOFT if on else PAPER, activebackground=ACCENT_SOFT if on else PAPER,
                       highlightbackground=ACCENT if on else LINE)

    # ---------- play screen ----------
    def build_play(self, parent):
        f = tk.Frame(parent, bg=CARD)
        f.columnconfigure(0, weight=1)

        top = tk.Frame(f, bg=CARD)
        top.grid(row=0, column=0, sticky="ew")
        self.attempt_label = label(top, "", 9, fg=MUTED)
        self.attempt_label.pack(side="left")
        self.level_label = label(top, "", 9, fg=MUTED)
        self.level_label.pack(side="right")

        self.dots = tk.Canvas(f, height=10, bg=CARD, highlightthickness=0)
        self.dots.grid(row=1, column=0, sticky="ew", pady=(4, 8))

        # the live range bar
        self.range_canvas = tk.Canvas(f, height=36, bg=CARD, highlightthickness=0)
        self.range_canvas.grid(row=2, column=0, sticky="ew")
        self.range_canvas.bind("<Configure>", lambda e: self.draw_range())

        ends = tk.Frame(f, bg=CARD)
        ends.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ends.columnconfigure(0, weight=1); ends.columnconfigure(1, weight=1)
        self.lo_num = label(ends, "1", 26, "bold")
        self.lo_num.grid(row=0, column=0, sticky="w")
        label(ends, "at least", 9, fg=MUTED).grid(row=1, column=0, sticky="w")
        self.hi_num = label(ends, "100", 26, "bold")
        self.hi_num.grid(row=0, column=1, sticky="e")
        label(ends, "at most", 9, fg=MUTED).grid(row=1, column=1, sticky="e")

        self.feedback = label(f, "", 12, "bold", justify="left", anchor="w")
        self.feedback.grid(row=4, column=0, sticky="ew", pady=(12, 10), ipady=4)
        f.bind("<Configure>", lambda e: self.feedback.config(wraplength=max(120, e.width - 4)))

        row = tk.Frame(f, bg=CARD)
        row.grid(row=5, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        self.guess_var = tk.StringVar()
        self.guess_entry = make_entry(row, textvariable=self.guess_var)
        self.guess_entry.grid(row=0, column=0, sticky="ew", ipady=6, padx=(0, 10))
        self.guess_entry.bind("<Return>", lambda e: self.submit_guess())
        self.guess_btn = make_button(row, "Guess", self.submit_guess)
        self.guess_btn.grid(row=0, column=1)

        self.history = tk.Text(f, height=3, wrap="word", font=(FONT, 11, "bold"), bg=CARD, relief="flat",
                               highlightthickness=0, state="disabled", cursor="arrow", takefocus=0)
        for tag, color in (("low", LOW), ("high", HIGH), ("correct", WIN)):
            self.history.tag_configure(tag, foreground=color)
        self.history.grid(row=6, column=0, sticky="ew", pady=(14, 0))

        self.again_row = tk.Frame(f, bg=CARD)
        self.again_row.grid(row=7, column=0, sticky="w", pady=(14, 0))
        make_button(self.again_row, "Play again", self.start_game).pack(side="left")
        make_button(self.again_row, "Change settings", self.show_setup, primary=False).pack(side="left", padx=(10, 0))
        self.again_row.grid_remove()
        return f

    def show_setup(self):
        self.play_frame.grid_remove()
        self.setup_frame.grid()

    # ---------- game flow ----------
    def start_game(self):
        player = self.name_var.get().strip()[:20] or "Anonymous"
        self.game = self.db.new_game(player, self.level)
        self.guess_list = []
        self.shown = (1.0, float(self.game["max_number"]))
        self.setup_frame.grid_remove()
        self.play_frame.grid()
        self.again_row.grid_remove()
        self.guess_entry.config(state="normal")
        self.guess_btn.config(state="normal")
        self.guess_var.set("")
        self.say("Take your first guess.", INK)
        self.update_play(animate=False)
        self.guess_entry.focus_set()

    def submit_guess(self):
        if not self.game or self.game["status"] != "playing":
            return
        try:
            value = int(self.guess_var.get().strip())
        except ValueError:
            return self.say("Enter a whole number.", LOSE)
        top = self.game["max_number"]
        if not 1 <= value <= top:
            return self.say(f"Pick a number between 1 and {top}.", LOSE)

        result, self.game = self.db.make_guess(self.game["id"], value)
        self.guess_list.append((value, result))
        self.guess_var.set("")
        g = self.game
        left = g["max_attempts"] - g["attempts"]

        if g["status"] == "won":
            n = g["attempts"]
            self.say(f"Correct! It was {g['secret']}. You scored {g['score']} points in "
                     f"{n} {'guess' if n == 1 else 'guesses'}.", WIN)
        elif g["status"] == "lost":
            self.say(f"Out of guesses. The number was {g['secret']}.", LOSE)
        elif result == "low":
            self.say(f"{value} is too low, go higher. {left} {'guess' if left == 1 else 'guesses'} left.", LOW)
        else:
            self.say(f"{value} is too high, go lower. {left} {'guess' if left == 1 else 'guesses'} left.", HIGH)

        self.update_play()
        if g["status"] != "playing":
            self.guess_entry.config(state="disabled")
            self.guess_btn.config(state="disabled")
            self.again_row.grid()
            self.refresh_board()
        else:
            self.guess_entry.focus_set()

    def say(self, text, color):
        self.feedback.config(text=text, fg=color)

    # ---------- drawing ----------
    def update_play(self, animate=True):
        g = self.game
        self.lo_num.config(text=str(g["low"]))
        self.hi_num.config(text=str(g["high"]))
        shown_attempt = min(g["attempts"] + 1, g["max_attempts"])
        self.attempt_label.config(text=f"Guess {shown_attempt} of {g['max_attempts']}")
        self.level_label.config(text=f"{g['difficulty']}, 1 to {g['max_number']}")

        self.dots.delete("all")
        for i in range(g["max_attempts"]):
            x = i * 29
            self.dots.create_rectangle(x, 2, x + 24, 8, width=0, fill=INK if i < g["attempts"] else LINE)

        self.history.config(state="normal")
        self.history.delete("1.0", "end")
        for value, result in self.guess_list:
            self.history.insert("end", f" {value}   ", result)
        self.history.config(state="disabled")

        if animate:
            self.animate_range(float(g["low"]), float(g["high"]))
        else:
            self.shown = (float(g["low"]), float(g["high"]))
            self.draw_range()

    def animate_range(self, target_lo, target_hi, steps=14):
        if self.anim_id:
            self.after_cancel(self.anim_id)
        start_lo, start_hi = self.shown

        def step(i):
            e = 1 - (1 - i / steps) ** 3          # ease-out
            self.shown = (start_lo + (target_lo - start_lo) * e, start_hi + (target_hi - start_hi) * e)
            self.draw_range()
            self.anim_id = self.after(16, step, i + 1) if i < steps else None

        step(1)

    def draw_range(self):
        c = self.range_canvas
        if not self.game:
            return
        w, h = c.winfo_width(), c.winfo_height()
        n = self.game["max_number"]
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill=PAPER, outline=LINE)
        lo, hi = self.shown
        x0, x1 = (lo - 1) / n * w, hi / n * w
        c.create_rectangle(x0, 1, max(x1, x0 + 3), h - 1, fill=ACCENT, width=0)
        for value, _ in self.guess_list:                      # a tick for every past guess
            x = (value - 0.5) / n * w
            c.create_line(x, 0, x, h, fill=INK, width=2)

    # ---------- leaderboard ----------
    def refresh_board(self):
        for child in self.board_rows.winfo_children():
            child.destroy()
        scores = self.db.top_scores(5 if self.wide else 3)
        if not scores:
            label(self.board_rows, "No wins yet. Be the first on the board.", 10, fg=MUTED,
                  wraplength=220, justify="left").pack(anchor="w")
        for i, r in enumerate(scores, 1):
            row = tk.Frame(self.board_rows, bg=CARD)
            row.pack(fill="x", pady=4)
            row.columnconfigure(0, weight=1)
            label(row, f"{i}. {r['player']}", 11, "bold").grid(row=0, column=0, sticky="w")
            n = r["attempts"]
            label(row, f"{r['difficulty']}, {n} {'guess' if n == 1 else 'guesses'}", 9, fg=MUTED
                  ).grid(row=1, column=0, sticky="w")
            label(row, str(r["score"]), 18, "bold").grid(row=0, column=1, rowspan=2, sticky="e")
        played, won = self.db.stats()
        self.stats_label.config(text=f"{won} won out of {played} finished games." if played else "")

    def on_close(self):
        self.db.conn.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()