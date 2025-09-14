# streamlit_app.py
# pip install streamlit pdfplumber pandas openpyxl PyPDF2

import streamlit as st
import pandas as pd
import tempfile
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter
import pdfplumber
import re

DATE_LINE_RE = re.compile(
    r'^[A-Za-z]{3}\s+\d{1,2},\s*\d{4}\s+.*(Debit|Credit)\s+INR\s+([\d,]+\.\d{2}|\d+)', re.IGNORECASE)
TIME_TID_RE = re.compile(r'^(\d{1,2}:\d{2}\s*(?:AM|PM))\s+Transaction ID\s*:\s*(\S+)', re.IGNORECASE)
UTR_RE = re.compile(r'^UTR No\s*:\s*(\S+)', re.IGNORECASE)

def unlock_pdf(in_memory_bytes, password):
    reader = PdfReader(in_memory_bytes)
    if not reader.is_encrypted:
        return in_memory_bytes
    if not password:
        raise ValueError("Password required")
    if reader.decrypt(password) == 0:
        raise ValueError("Incorrect password")
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(tmp.name, "wb") as f:
        writer.write(f)
    return tmp.name

def extract_lines(path_or_bytes):
    lines = []
    with pdfplumber.open(path_or_bytes) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            for raw in text.splitlines():
                line = raw.strip()
                if line and not line.startswith("Date Transaction Details") and "support.phonepe.com" not in line:
                    lines.append(line)
    return lines

def parse_transactions(lines):
    records = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if DATE_LINE_RE.match(line):
            parts = line.split()
            date = " ".join(parts[0:3])
            # find debit/credit token index
            txn_type_idx = None
            for j in range(len(parts)-1, -1, -1):
                if parts[j].lower() in ("debit","credit"):
                    txn_type_idx = j
                    break
            if txn_type_idx is None:
                i += 1; continue
            details = " ".join(parts[3:txn_type_idx])
            txn_type = parts[txn_type_idx].title()
            amount = parts[-1].replace(",","")
            time = tid = utr = ""
            if i+1 < len(lines):
                m_time = TIME_TID_RE.match(lines[i+1])
                if m_time:
                    time = m_time.group(1); tid = m_time.group(2)
            if i+2 < len(lines):
                m_utr = UTR_RE.match(lines[i+2])
                if m_utr:
                    utr = m_utr.group(1)
            records.append({
                "Date & Time": f"{date} {time}".strip(),
                "Transaction Details": details,
                "Transaction ID": tid,
                "UTR No": utr,
                "Type": txn_type,
                "Amount": amount
            })
            step = 3
            if i+3 < len(lines) and (lines[i+3].lower().startswith("debited from") or lines[i+3].lower().startswith("credited to")):
                step = 4
            i += step
        else:
            i += 1
    return pd.DataFrame(records)

st.title("PhonePe PDF → CSV / Excel")
uploaded = st.file_uploader("Upload PhonePe PDF", type="pdf")
password = st.text_input("Password (if encrypted)", type="password")
fmt = st.radio("Output format", ["csv","excel"])
if uploaded:
    if st.button("Convert"):
        try:
            tmp_path = None
            # try to open in-memory. If encrypted, use unlock
            try:
                reader = PdfReader(uploaded)
                if reader.is_encrypted:
                    if not password:
                        st.error("PDF is encrypted — please provide password")
                        st.stop()
                    if reader.decrypt(password) == 0:
                        st.error("Incorrect password")
                        st.stop()
                    # write unlocked temp
                    writer = PdfWriter()
                    for p in reader.pages:
                        writer.add_page(p)
                    tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                    with open(tmpf.name, "wb") as f:
                        writer.write(f)
                    tmp_path = tmpf.name
                    source = tmp_path
                else:
                    # write uploaded bytes to temp file for pdfplumber
                    tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                    tmpf.write(uploaded.getbuffer())
                    tmpf.close()
                    tmp_path = tmpf.name
                    source = tmp_path
            except Exception as e:
                st.error("Failed to open PDF: " + str(e))
                st.stop()

            lines = extract_lines(source)
            df = parse_transactions(lines)
            if df.empty:
                st.warning("No transactions parsed — PDF structure may differ.")
            else:
                st.write("Preview:")
                st.dataframe(df.head(10))
                if fmt == "csv":
                    st.download_button("Download CSV", data=df.to_csv(index=False).encode("utf-8"),
                                       file_name="phonepe_transactions.csv", mime="text/csv")
                else:
                    # write to bytes
                    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                    df.to_excel(tmp_out.name, index=False)
                    with open(tmp_out.name, "rb") as f:
                        st.download_button("Download Excel", data=f.read(), file_name="phonepe_transactions.xlsx")
                    os.remove(tmp_out.name)
            if tmp_path:
                try: os.remove(tmp_path)
                except: pass
        except Exception as e:
            st.error("Error: " + str(e))
