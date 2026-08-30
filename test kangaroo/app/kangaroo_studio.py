"""
Kangaroo Studio — a Windows desktop app for the full learn-and-automate flow:

    1. Region   pick any screen area (drag, like a screen-capture tool)
    2. Record   capture your screen + clicks in that area
    3. Train    learn a screen -> click model, and REVIEW what it learned
    4. Check    dry-run: see where it WOULD click, no real clicks
    5. Run      execute the automation for real (with fail-safes)

Built on Tkinter (ships with Python — nothing extra to install for the GUI).
It drives the verified scripts in ../rpa via subprocess and streams their output
into the log, so the GUI stays thin and the logic stays tested.

Run:   python app/kangaroo_studio.py       (from the "test kangaroo" folder)
       or double-click app/run_studio.bat on Windows.

Only automate your own machine and workflows. Use F9 in the recorder to pause
before typing anything private; the runner's fail-safe stops on a corner or Esc.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
RPA = os.path.normpath(os.path.join(HERE, "..", "rpa"))
SESSIONS = os.path.join(RPA, "sessions")
PY = sys.executable or "python"

BG = "#0d1417"
PANEL = "#131d21"
LINE = "#213136"
INK = "#e2edec"
MUTE = "#8ba1a2"
ACCENT = "#33e2c4"
RUN = "#34d38b"
STOP = "#f26073"

PRESETS = [
    ("Small  640 × 360", (640, 360)),
    ("Medium 960 × 540", (960, 540)),
    ("Large  1280 × 720", (1280, 720)),
    ("Full screen", None),
]


class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kangaroo Studio")
        self.configure(bg=BG)
        self.geometry("860x620")
        self.minsize(760, 560)
        self.region = None                 # (left, top, w, h)
        self.q = queue.Queue()
        self.proc = None

        self._style()
        self._build()
        self.refresh_sessions()
        self.after(100, self._poll)

    # ---------- styling ----------
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        s.configure("Card.TLabel", background=PANEL, foreground=INK, font=("Segoe UI", 10))
        s.configure("H.TLabel", background=PANEL, foreground=ACCENT,
                    font=("Segoe UI Semibold", 11))
        s.configure("Mute.TLabel", background=PANEL, foreground=MUTE, font=("Segoe UI", 9))
        s.configure("TButton", font=("Segoe UI", 10), padding=7)
        s.configure("TCombobox", fieldbackground=BG, background=BG)
        s.configure("TSpinbox", fieldbackground=BG, foreground=INK)

    def _card(self, parent, step, title):
        wrap = ttk.Frame(parent, style="Card.TFrame")
        wrap.pack(fill="x", pady=6, ipady=4)
        head = ttk.Frame(wrap, style="Card.TFrame")
        head.pack(fill="x", padx=12, pady=(9, 2))
        ttk.Label(head, text=f"{step}", style="H.TLabel").pack(side="left")
        ttk.Label(head, text=title, style="H.TLabel").pack(side="left", padx=(8, 0))
        body = ttk.Frame(wrap, style="Card.TFrame")
        body.pack(fill="x", padx=12, pady=(2, 10))
        return body

    # ---------- layout ----------
    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=14, pady=(12, 4))
        ttk.Label(header, text="Kangaroo Studio",
                  font=("Segoe UI Semibold", 16)).pack(side="left")
        ttk.Label(header, text="capture · learn · automate", style="TLabel",
                  foreground=MUTE).pack(side="left", padx=10)

        cols = ttk.Frame(self)
        cols.pack(fill="both", expand=True, padx=14, pady=6)
        left = ttk.Frame(cols)
        left.pack(side="left", fill="both", expand=True)

        # 1 region
        b = self._card(left, "1", "Region")
        ttk.Button(b, text="Select on screen (drag)", command=self.select_region)\
            .grid(row=0, column=0, sticky="w")
        self.preset = ttk.Combobox(b, values=[p[0] for p in PRESETS],
                                   state="readonly", width=20)
        self.preset.grid(row=0, column=1, padx=8)
        self.preset.bind("<<ComboboxSelected>>", self.pick_preset)
        self.region_lbl = ttk.Label(b, text="no region selected", style="Mute.TLabel")
        self.region_lbl.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # 2 record
        b = self._card(left, "2", "Record your workflow")
        ttk.Button(b, text="Start recording", command=self.start_record)\
            .grid(row=0, column=0, sticky="w")
        ttk.Label(b, text="A window records your screen + clicks. Esc = stop, F9 = pause.",
                  style="Mute.TLabel").grid(row=1, column=0, columnspan=3, sticky="w",
                                            pady=(6, 0))

        # 3 train
        b = self._card(left, "3", "Train & review")
        ttk.Label(b, text="Session:", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.session = ttk.Combobox(b, state="readonly", width=26)
        self.session.grid(row=0, column=1, padx=6)
        ttk.Button(b, text="↻", width=3, command=self.refresh_sessions)\
            .grid(row=0, column=2)
        ttk.Button(b, text="Build + Train", command=self.train)\
            .grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(b, text="Open review images", command=self.open_review)\
            .grid(row=1, column=1, sticky="w", pady=(8, 0))

        # 4/5 run
        b = self._card(left, "4·5", "Check, then run")
        ttk.Label(b, text="Interval (s):", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.interval = ttk.Spinbox(b, from_=0.2, to=10, increment=0.2, width=6)
        self.interval.set("1.0")
        self.interval.grid(row=0, column=1, sticky="w")
        ttk.Label(b, text="Max actions:", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.maxact = ttk.Spinbox(b, from_=1, to=500, width=6)
        self.maxact.set("20")
        self.maxact.grid(row=0, column=3, sticky="w", padx=(4, 0))
        ttk.Button(b, text="Dry run (check where it clicks)", command=lambda: self.run(True))\
            .grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        run_btn = tk.Button(b, text="▶ Run for real", command=lambda: self.run(False),
                            bg=RUN, fg="#04211d", font=("Segoe UI Semibold", 10),
                            relief="flat", padx=10, pady=6, activebackground=ACCENT)
        run_btn.grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0), padx=(6, 0))
        tk.Button(b, text="■ Stop", command=self.stop_proc, bg=PANEL, fg=STOP,
                  relief="flat", padx=10).grid(row=2, column=0, sticky="w", pady=(8, 0))

        # log
        logwrap = ttk.Frame(self)
        logwrap.pack(fill="both", expand=True, padx=14, pady=(2, 6))
        ttk.Label(logwrap, text="Log", style="TLabel", foreground=MUTE).pack(anchor="w")
        self.logbox = tk.Text(logwrap, height=10, bg="#0a1215", fg=INK,
                              insertbackground=INK, relief="flat",
                              font=("Consolas", 9), wrap="word")
        self.logbox.pack(fill="both", expand=True)

        self.status = ttk.Label(self, text="ready", style="TLabel", foreground=MUTE)
        self.status.pack(fill="x", padx=14, pady=(0, 8))
        self.log("Kangaroo Studio ready. Start at step 1.\n")

    # ---------- region ----------
    def pick_preset(self, _=None):
        name = self.preset.get()
        size = dict(PRESETS)[name]
        if size is None:
            self.region = self._full_region()
        else:
            w, h = size
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.region = ((sw - w) // 2, (sh - h) // 2, w, h)  # centered
        self._show_region()

    def _full_region(self):
        return (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())

    def select_region(self):
        ov = tk.Toplevel(self)
        ov.attributes("-fullscreen", True)
        try:
            ov.attributes("-alpha", 0.30)
        except tk.TclError:
            pass
        ov.configure(bg="black")
        ov.attributes("-topmost", True)
        cv = tk.Canvas(ov, cursor="cross", bg="gray15", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_text(cv.winfo_screenwidth() // 2, 40,
                       text="Drag to select a region   ·   Esc to cancel",
                       fill=ACCENT, font=("Segoe UI", 14))
        st = {}

        def down(e):
            st["x"], st["y"] = e.x, e.y
            st["id"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline=ACCENT, width=2)

        def drag(e):
            if "id" in st:
                cv.coords(st["id"], st["x"], st["y"], e.x, e.y)

        def up(e):
            if "x" not in st:
                return
            left, top = min(st["x"], e.x), min(st["y"], e.y)
            w, h = abs(e.x - st["x"]), abs(e.y - st["y"])
            ov.destroy()
            if w > 8 and h > 8:
                self.region = (left, top, w, h)
                self._show_region()

        cv.bind("<Button-1>", down)
        cv.bind("<B1-Motion>", drag)
        cv.bind("<ButtonRelease-1>", up)
        ov.bind("<Escape>", lambda e: ov.destroy())

    def _show_region(self):
        self._region_str()  # validate
        l, t, w, h = self.region
        self.region_lbl.configure(text=f"region  left {l}, top {t},  {w} × {h} px",
                                  foreground=ACCENT)
        self.status.configure(text="region set")

    def _region_str(self):
        if not self.region:
            raise ValueError
        return ",".join(str(int(v)) for v in self.region)

    # ---------- actions ----------
    def _need_region(self):
        if not self.region:
            messagebox.showwarning("No region", "Pick a screen region in step 1 first.")
            return False
        return True

    def start_record(self):
        if not self._need_region():
            return
        self.run_sequence([[PY, os.path.join(RPA, "record_session.py"),
                            "--region", self._region_str()]],
                          note="recording — switch to your task window; press Esc to stop")

    def train(self):
        sess = self._session_dir()
        if not sess:
            return
        self.run_sequence([
            [PY, os.path.join(RPA, "build_dataset.py"), sess],
            [PY, os.path.join(RPA, "train_clicker.py"), sess],
        ], note="building dataset and training…")

    def run(self, dry):
        if not self._need_region():
            return
        sess = self._session_dir()
        if not sess:
            return
        model = os.path.join(sess, "clicker.pt")
        if not os.path.exists(model):
            messagebox.showwarning("No model", "Train a model in step 3 first.")
            return
        if not dry and not messagebox.askyesno(
                "Run for real?",
                "The agent will move your mouse and click.\n"
                "Move the mouse to a screen corner (or press Esc) to abort.\n\nContinue?"):
            return
        args = [PY, os.path.join(RPA, "run_agent.py"), "--model", model,
                "--region", self._region_str(),
                "--interval", str(self.interval.get()),
                "--max-actions", str(self.maxact.get())]
        if dry:
            args.append("--dry-run")
        self.run_sequence([args], note="dry run…" if dry else "RUNNING for real…")

    def stop_proc(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.log("[stopped]\n")
        self.status.configure(text="stopped")

    def open_review(self):
        sess = self._session_dir()
        if not sess:
            return
        rv = os.path.join(sess, "review")
        if not os.path.isdir(rv):
            messagebox.showinfo("No review yet", "Train a model first (step 3).")
            return
        try:
            if os.name == "nt":
                os.startfile(rv)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", rv])
            else:
                subprocess.Popen(["xdg-open", rv])
        except Exception as e:
            self.log(f"could not open folder: {e}\n")

    # ---------- sessions ----------
    def refresh_sessions(self):
        os.makedirs(SESSIONS, exist_ok=True)
        names = sorted((d for d in os.listdir(SESSIONS)
                        if os.path.isdir(os.path.join(SESSIONS, d))), reverse=True)
        self.session["values"] = names
        if names and not self.session.get():
            self.session.set(names[0])

    def _session_dir(self):
        name = self.session.get()
        if not name:
            messagebox.showwarning("No session", "Record a session, then pick it in step 3.")
            return None
        return os.path.join(SESSIONS, name)

    # ---------- subprocess plumbing ----------
    def run_sequence(self, cmds, note=""):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("Busy", "Something is already running. Stop it first.")
            return
        self.status.configure(text=note or "working…")

        def worker():
            for cmd in cmds:
                self.q.put("$ " + " ".join(os.path.basename(c) if i == 1 else c
                                           for i, c in enumerate(cmd)) + "\n")
                try:
                    self.proc = subprocess.Popen(
                        cmd, cwd=RPA, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, bufsize=1)
                except Exception as e:
                    self.q.put(f"[failed to start: {e}]\n")
                    return
                for line in self.proc.stdout:
                    self.q.put(line)
                code = self.proc.wait()
                self.q.put(f"[exit {code}]\n")
                if code != 0:
                    break
            self.q.put("__DONE__")

        threading.Thread(target=worker, daemon=True).start()

    def log(self, text):
        self.logbox.insert("end", text)
        self.logbox.see("end")

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item == "__DONE__":
                    self.status.configure(text="done")
                else:
                    self.log(item)
        except queue.Empty:
            pass
        self.after(100, self._poll)


if __name__ == "__main__":
    Studio().mainloop()
