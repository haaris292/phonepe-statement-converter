# streamlit_app.py
# pip install streamlit pdfplumber pandas openpyxl PyPDF2

import streamlit as st
import pandas as pd
import tempfile
import pdfplumber
from PyPDF2 import PdfReader, PdfWriter
import re
import os

# ---------------- REGEX ----------------
DATE_RE = re.compile(r'[A-Za-z]{3}\s+\d{1,2},\s*\d{4}')
TIME_RE = re.compile(r'\d{1,2}:\d{2}\s*(AM|PM)', re.IGNORECASE)
AMOUNT_RE = re.compile(r'(Debit|Credit)\s+INR\s+([\d,]+\.\d{2})', re.IGNORECASE)
TID_RE = re.compile(r'Transaction ID\s*:\s*(\S+)')
UTR_RE = re.compile(r'UTR No\s*:\s*(\S+)')

# ---------------- HELPERS ----------------
def unlock_pdf(path, password):
    reader = PdfReader(path)
    if not reader.is_encrypted:
        return path

    if not password:
        raise ValueError("PDF is encrypted. Password required.")

    if reader.decrypt(password) == 0:
        raise ValueError("Incorrect PDF password.")

    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(tmp.name, "wb") as f:
        writer.write(f)
    return tmp.name


def extract_lines(pdf_path):
    lines = []
    with pdfplumber.open(pdf_path, laparams={"detect_vertical": False}) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if "support.phonepe.com" in line:
                    continue
                if line.lower().startswith("page ") and "of" in line.lower():
                    continue
                lines.append(line)
    return lines


def parse_transactions(lines):
    records = []
    current = {}

    for line in lines:
        if DATE_RE.search(line):
            current["Date"] = DATE_RE.search(line).group()

        if "Paid to" in line or "Received from" in line:
            current["Details"] = line.replace(current.get("Date", ""), "").strip()

        amt = AMOUNT_RE.search(line)
        if amt:
            current["Type"] = amt.group(1).title()
            current["Amount"] = amt.group(2).replace(",", "")

        time = TIME_RE.search(line)
        if time:
            current["Time"] = time.group()

        tid = TID_RE.search(line)
        if tid:
            current["Transaction ID"] = tid.group(1)

        utr = UTR_RE.search(line)
        if utr:
            current["UTR No"] = utr.group(1)

            # Transaction COMPLETE at UTR
            records.append({
                "Date & Time": f"{current.get('Date','')} {current.get('Time','')}".strip(),
                "Transaction Details": current.get("Details",""),
                "Transaction ID": current.get("Transaction ID",""),
                "UTR No": current.get("UTR No",""),
                "Type": current.get("Type",""),
                "Amount": current.get("Amount","")
            })
            current = {}

    return pd.DataFrame(records)


# ---------------- UI ----------------
st.set_page_config(page_title="PhonePe PDF Converter", page_icon="💳")
st.title("💳 PhonePe PDF → CSV / Excel Converter")

st.markdown("""
### ℹ️ How to use
1. Upload your **PhonePe PDF statement**
2. Enter password **only if the PDF is locked**
3. Click **Convert**
4. Preview and download CSV / Excel

🔐 Files are processed in memory and never stored.
""")

uploaded = st.file_uploader("📂 Upload PhonePe PDF", type="pdf")
password = st.text_input("🔑 PDF Password (if any)", type="password")
fmt = st.radio("📄 Output format", ["csv", "excel"])

if uploaded and st.button("🚀 Convert"):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.getbuffer())
            source = tmp.name

        source = unlock_pdf(source, password)

        lines = extract_lines(source)
        df = parse_transactions(lines)

        if df.empty:
            st.error("❌ No transactions found. PDF format may be unsupported.")
        else:
            st.success(f"✅ Parsed {len(df)} transactions")
            st.dataframe(df.head(10))

            if fmt == "csv":
                st.download_button(
                    "⬇️ Download CSV",
                    df.to_csv(index=False).encode("utf-8"),
                    "phonepe_transactions.csv",
                    "text/csv"
                )
            else:
                out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                df.to_excel(out.name, index=False)
                with open(out.name, "rb") as f:
                    st.download_button(
                        "⬇️ Download Excel",
                        f.read(),
                        "phonepe_transactions.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                os.remove(out.name)

        os.remove(source)

    except Exception as e:
        st.error(str(e))
