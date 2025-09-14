#!/usr/bin/env python3
"""
phonepe_converter_app.py

Desktop app (Tkinter) to:
 - optionally unlock a password-protected PhonePe PDF (user-entered password)
 - parse PhonePe transaction statement
 - export to CSV or Excel

Dependencies:
    pip install pdfplumber pandas openpyxl PyPDF2
"""

import re
import tempfile
import os
import sys
from pathlib import Path
import shutil

import pdfplumber
import pandas as pd
from PyPDF2 import PdfReader, PdfWriter

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# -------------------------
# PDF unlocking helper
# -------------------------
def unlock_pdf_if_encrypted(input_path: Path, password: str | None) -> Path:
    """
    If input_path is encrypted, try to decrypt with password.
    Returns path to a PDF file that is not encrypted (may be original).
    Raises ValueError on decryption failure.
    """
    reader = PdfReader(str(input_path))
    if not reader.is_encrypted:
        return input_path

    if not password:
        raise ValueError("PDF is encrypted but no password provided.")

    # try decrypt
    try:
        if reader.decrypt(password) == 0:
            # PyPDF2 returns 0 on failure
            raise ValueError("Incorrect password for encrypted PDF.")
    except Exception as e:
        raise ValueError("Failed to decrypt PDF: " + str(e))

    # write a temporary decrypted copy
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.close()
    with open(tmp.name, "wb") as fout:
        writer.write(fout)

    return Path(tmp.name)


# -------------------------
# Parser (robust for PhonePe format)
# -------------------------
DATE_LINE_RE = re.compile(
    r'^[A-Za-z]{3}\s+\d{1,2},\s*\d{4}\s+.*(Debit|Credit)\s+INR\s+([\d,]+\.\d{2}|\d+)', re.IGNORECASE)
TIME_TID_RE = re.compile(r'^(\d{1,2}:\d{2}\s*(?:AM|PM))\s+Transaction ID\s*:\s*(\S+)', re.IGNORECASE)
UTR_RE = re.compile(r'^UTR No\s*:\s*(\S+)', re.IGNORECASE)


def extract_lines(pdf_path: str) -> list:
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                # filter repeated header/footer lines
                if line.startswith("Date Transaction Details") or line.startswith("This is a system generated statement"):
                    continue
                if "support.phonepe.com" in line:
                    continue
                # ignore page footers
                if line.lower().startswith("page ") and "of" in line.lower():
                    continue
                lines.append(line)
    return lines


def parse_transactions(lines: list) -> pd.DataFrame:
    records = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if DATE_LINE_RE.match(line):
            parts = line.split()
            # first 3 tokens are date (Mon dd, yyyy)
            if len(parts) < 5:
                # malformed
                i += 1
                continue
            date = " ".join(parts[0:3])  # e.g., Jun 03, 2025
            # details between date and Debit/Credit tokens
            # Find the position of Debit/Credit token (last occurrence of Debit/Credit)
            txn_type_token_index = None
            for idx in range(len(parts)-1, -1, -1):
                if parts[idx].lower() in ("debit", "credit"):
                    txn_type_token_index = idx
                    break
            if txn_type_token_index is None or txn_type_token_index < 3:
                i += 1
                continue
            details = " ".join(parts[3:txn_type_token_index])
            txn_type = parts[txn_type_token_index].title()
            # amount is last token
            amount = parts[-1].replace(",", "")

            # Next line: Time + Transaction ID
            tid = ""
            time = ""
            if i + 1 < len(lines):
                m_time = TIME_TID_RE.match(lines[i + 1])
                if m_time:
                    time = m_time.group(1)
                    tid = m_time.group(2)
                else:
                    # If not match, try to find "Transaction ID" substring
                    if "Transaction ID" in lines[i + 1]:
                        # extract after colon
                        parts2 = lines[i + 1].split("Transaction ID")
                        if len(parts2) > 1:
                            tid = parts2[1].replace(":", "").strip()
                            # try extracting time if present at start
                            time_search = re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM)', lines[i + 1], re.IGNORECASE)
                            if time_search:
                                time = time_search.group(0)

            # Next line: UTR
            utr = ""
            if i + 2 < len(lines):
                m_utr = UTR_RE.match(lines[i + 2])
                if m_utr:
                    utr = m_utr.group(1)
            # Optional: skip "Debited from ..." line at i+3

            datetime_str = f"{date} {time}".strip()
            records.append({
                "Date & Time": datetime_str,
                "Transaction Details": details.strip(),
                "Transaction ID": tid,
                "UTR No": utr,
                "Type": txn_type,
                "Amount": amount
            })

            # Advance index: skip optional "Debited from ..." if present
            step = 3
            if i + 3 < len(lines) and (lines[i+3].lower().startswith("debited from") or lines[i+3].lower().startswith("credited to")):
                step = 4
            i += step
        else:
            i += 1

    df = pd.DataFrame(records, columns=["Date & Time", "Transaction Details", "Transaction ID", "UTR No", "Type", "Amount"])
    # keep IDs as strings
    df["Transaction ID"] = df["Transaction ID"].astype(str)
    df["UTR No"] = df["UTR No"].astype(str)
    return df


def save_output(df: pd.DataFrame, output_path: Path, fmt: str):
    fmt = fmt.lower()
    if df.empty:
        raise ValueError("No transactions parsed.")
    if fmt == "csv":
        # prefix IDs with single quote so Excel treats them as text
        df_copy = df.copy()
        df_copy["Transaction ID"] = df_copy["Transaction ID"].apply(lambda x: ("'" + x) if x else x)
        df_copy["UTR No"] = df_copy["UTR No"].apply(lambda x: ("'" + x) if x else x)
        out_file = output_path.with_suffix(".csv")
        df_copy.to_csv(out_file, index=False)
    else:
        out_file = output_path.with_suffix(".xlsx")
        df.to_excel(out_file, index=False)
    return out_file


# -------------------------
# Tkinter GUI
# -------------------------
class PhonePeConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PhonePe Statement Converter")
        self.geometry("760x540")
        self.resizable(False, False)

        self.pdf_path: Path | None = None
        self.temp_unlocked: Path | None = None

        # UI elements
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        # Row: file selection
        row = ttk.Frame(frame)
        row.pack(fill=tk.X, pady=6)
        ttk.Label(row, text="PDF File:").pack(side=tk.LEFT)
        self.file_label = ttk.Label(row, text="(no file selected)", width=70)
        self.file_label.pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="Browse...", command=self.browse_file).pack(side=tk.RIGHT)

        # Row: password
        row2 = ttk.Frame(frame)
        row2.pack(fill=tk.X, pady=6)
        ttk.Label(row2, text="Password (if encrypted):").pack(side=tk.LEFT)
        self.pw_entry = ttk.Entry(row2, show="*", width=30)
        self.pw_entry.pack(side=tk.LEFT, padx=6)
        ttk.Label(row2, text="(leave empty if not encrypted)").pack(side=tk.LEFT)

        # Row: output options
        row3 = ttk.Frame(frame)
        row3.pack(fill=tk.X, pady=6)
        ttk.Label(row3, text="Output filename:").pack(side=tk.LEFT)
        self.out_entry = ttk.Entry(row3, width=45)
        self.out_entry.insert(0, "phonepe_transactions")
        self.out_entry.pack(side=tk.LEFT, padx=6)
        # format radio
        self.format_var = tk.StringVar(value="csv")
        ttk.Radiobutton(row3, text="CSV", variable=self.format_var, value="csv").pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(row3, text="Excel", variable=self.format_var, value="excel").pack(side=tk.LEFT, padx=6)

        # Row: action buttons
        row4 = ttk.Frame(frame)
        row4.pack(fill=tk.X, pady=8)
        self.convert_btn = ttk.Button(row4, text="Convert", command=self.on_convert)
        self.convert_btn.pack(side=tk.LEFT)
        ttk.Button(row4, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=8)
        ttk.Button(row4, text="Exit", command=self.on_exit).pack(side=tk.RIGHT)

        # Row: preview/log area
        ttk.Label(frame, text="Log / Preview:").pack(anchor=tk.W)
        self.log = scrolledtext.ScrolledText(frame, height=22, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)

    def browse_file(self):
        path = filedialog.askopenfilename(title="Select PhonePe PDF", filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        self.pdf_path = Path(path)
        self.file_label.config(text=str(self.pdf_path))

    def log_print(self, *args):
        text = " ".join(str(a) for a in args)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def clear_log(self):
        self.log.delete("1.0", tk.END)

    def on_exit(self):
        # cleanup temp file if created
        try:
            if self.temp_unlocked and self.temp_unlocked.exists():
                os.remove(self.temp_unlocked)
        except Exception:
            pass
        self.destroy()

    def on_convert(self):
        if not self.pdf_path:
            messagebox.showwarning("No file", "Please select a PDF file first.")
            return
        out_name = self.out_entry.get().strip()
        if not out_name:
            messagebox.showwarning("No output filename", "Please enter an output filename.")
            return
        fmt = self.format_var.get()

        # disable button during processing (synchronous)
        self.convert_btn.config(state=tk.DISABLED)
        self.log_print("Starting conversion...")

        # ensure any previous temp file is removed
        try:
            if self.temp_unlocked and self.temp_unlocked.exists():
                os.remove(self.temp_unlocked)
                self.temp_unlocked = None
        except Exception:
            pass

        try:
            password = self.pw_entry.get().strip()
            # unlock if needed
            try:
                pdf_to_use = unlock_pdf_if_encrypted(self.pdf_path, password if password else None)
            except ValueError as exc:
                messagebox.showerror("Decryption failed", str(exc))
                self.log_print("Decryption failed:", exc)
                return
            # if a temp unlocked path was created, keep reference for cleanup
            if pdf_to_use != self.pdf_path:
                self.temp_unlocked = pdf_to_use

            self.log_print("Extracting text from PDF...")
            lines = extract_lines(str(pdf_to_use))
            self.log_print(f"Extracted {len(lines)} lines.")

            self.log_print("Parsing transactions...")
            df = parse_transactions(lines)
            self.log_print(f"Parsed {len(df)} transactions.")

            if df.empty:
                messagebox.showwarning("No data", "No transactions parsed — check PDF structure.")
                self.log_print("No transactions parsed. Aborting save.")
            else:
                # show a preview (first 10 rows)
                self.log_print("Preview (first 10 rows):")
                self.log_print(df.head(10).to_string(index=False))

                # prepare output path
                out_path = Path.cwd() / out_name
                out_file = save_output(df, out_path, fmt)
                messagebox.showinfo("Success", f"Saved {out_file}")
                self.log_print("Saved file:", out_file)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.log_print("Error:", repr(e))
        finally:
            # cleanup temp unlocked file (keep for debugging? we'll remove)
            try:
                if self.temp_unlocked and self.temp_unlocked.exists():
                    os.remove(self.temp_unlocked)
                    self.temp_unlocked = None
            except Exception:
                pass
            self.convert_btn.config(state=tk.NORMAL)


# -------------------------
# Run app
# -------------------------
def main():
    app = PhonePeConverterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
