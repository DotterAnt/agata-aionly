from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("runs/fixture-output.txt")
    root = tk.Tk()
    root.title("Desktop Agent Fixture")
    root.geometry("420x220+180+140")

    status = tk.StringVar(value="Ready")
    text = tk.StringVar()

    tk.Label(root, text="Message").place(x=30, y=34, width=80, height=26)
    entry = tk.Entry(root, textvariable=text)
    entry.place(x=120, y=34, width=240, height=28)
    entry.focus_set()

    def create_output() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text.get(), encoding="utf-8")
        status.set(f"Created {output.name}")

    tk.Button(root, text="Create Output", command=create_output).place(x=120, y=84, width=140, height=34)
    tk.Label(root, textvariable=status).place(x=30, y=145, width=350, height=26)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
