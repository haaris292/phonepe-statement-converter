# streamlit_app.py
# pip install streamlit pdfplumber pandas openpyxl PyPDF2

import streamlit as st
import pandas as pd
import tempfile
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter
import pdfplumber
import re
import os

DATE_LINE_RE = re.compile(
    r'^[A-Za-z]{3}\s+\d{1,2},\s*\d{4}\s+.*(Debit|Credit)\s+INR\s+([\d,]+\.\d{2}|\d+)', re.IGNORECASE)
TIME_TID_RE = re.compile(r'^(\d{1,2}:\d{2}\s*(?:AM|PM))\s+Transaction ID\s*:\s*(\S+)', re.IGNORECASE)
UTR_RE = re.compile(r'^UTR No\s*:\s*(\S+)', re.IGNORECASE)

# --- PDF helpers ---
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

# --- Streamlit UI ---
st.set_page_config(page_title="PhonePe PDF → CSV/Excel", page_icon="💳", layout="centered")

st.title("💳 PhonePe PDF → CSV / Excel Converter")

# How to use instructions
st.markdown("""
### ℹ️ How to use this tool
1. **Upload your PhonePe PDF statement** using the uploader below.  
2. If the PDF is **password-protected**, enter the password in the text box.  
3. Choose your preferred output format (**CSV** or **Excel**).  
4. Click **Convert**.  
5. Preview the first few rows of data, then download the full file.  

👉 *Note: Your data is processed locally in memory and not stored.*
""")

uploaded = st.file_uploader("📂 Upload PhonePe PDF", type="pdf")
password = st.text_input("🔑 Password (leave empty if not encrypted)", type="password")
fmt = st.radio("📄 Output format", ["csv","excel"])

if uploaded:
    if st.button("🚀 Convert"):
        try:
            # write uploaded file to a temp path
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmpf.write(uploaded.getbuffer())
            tmpf.close()
            source = tmpf.name

            # try reading
            reader = PdfReader(source)
            if reader.is_encrypted:
                if not password:
                    st.error("PDF is encrypted — please provide a password.")
                    st.stop()
                if reader.decrypt(password) == 0:
                    st.error("Incorrect password.")
                    st.stop()
                # decrypt to temp
                writer = PdfWriter()
                for p in reader.pages:
                    writer.add_page(p)
                tmp2 = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                with open(tmp2.name, "wb") as f:
                    writer.write(f)
                source = tmp2.name

            # extract + parse
            lines = extract_lines(source)
            df = parse_transactions(lines)
            if df.empty:
                st.warning("⚠️ No transactions parsed — check that the PDF format is supported.")
            else:
                st.success(f"✅ Parsed {len(df)} transactions.")
                st.dataframe(df.head(10))  # preview
                if fmt == "csv":
                    st.download_button("⬇️ Download CSV", data=df.to_csv(index=False).encode("utf-8"),
                                       file_name="phonepe_transactions.csv", mime="text/csv")
                else:
                    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                    df.to_excel(tmp_out.name, index=False)
                    with open(tmp_out.name, "rb") as f:
                        st.download_button("⬇️ Download Excel", data=f.read(),
                                           file_name="phonepe_transactions.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    os.remove(tmp_out.name)

            os.remove(source)
        except Exception as e:
            st.error("❌ Error: " + str(e))
