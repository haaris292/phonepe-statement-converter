# streamlit_app.py
# Requirements:
# pip install streamlit pdfplumber pandas openpyxl PyPDF2

import streamlit as st
import pandas as pd
import tempfile
import pdfplumber
from PyPDF2 import PdfReader, PdfWriter
import re
import os

# -------------------------------------------------
# Regex patterns (universal PhonePe support)
# -------------------------------------------------
DATE_RE = re.compile(r'[A-Za-z]{3}\s+\d{1,2},\s*\d{4}')
TIME_RE = re.compile(r'\d{1,2}[:￾]\d{2}\s*(am|pm)', re.IGNORECASE)
AMOUNT_RE = re.compile(r'(DEBIT|CREDIT)\s*[₹₹]?\s*([\d,]+)', re.IGNORECASE)
TID_RE = re.compile(r'Transaction ID\s*(?:\:)?\s*(\S+)', re.IGNORECASE)
UTR_RE = re.compile(r'UTR\s*No\.?\s*(?:\:)?\s*(\S+)', re.IGNORECASE)
DETAILS_RE = re.compile(
    r'(Paid to|Received from)\s+(.+?)\s+(DEBIT|CREDIT)',
    re.IGNORECASE | re.DOTALL
)

# -------------------------------------------------
# PDF helpers
# -------------------------------------------------
def try_extract_text(pdf_path):
    try:
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=2, y_tolerance=2)
                if t:
                    # normalize weird control characters
                    t = t.replace("￾", ":")
                    text += "\n" + t
        return text if text.strip() else None
    except Exception:
        return None


def unlock_pdf_if_needed(pdf_path, password):
    # First try reading directly
    text = try_extract_text(pdf_path)
    if text:
        return pdf_path, text

    reader = PdfReader(pdf_path)
    if not reader.is_encrypted:
        raise ValueError("PDF text could not be read.")

    if not password:
        raise ValueError("PDF appears restricted. Please provide password.")

    if reader.decrypt(password) == 0:
        raise ValueError("Incorrect PDF password.")

    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(tmp.name, "wb") as f:
        writer.write(f)

    text = try_extract_text(tmp.name)
    if not text:
        raise ValueError("Unable to extract text even after decryption.")

    return tmp.name, text


# -------------------------------------------------
# Universal transaction parser
# -------------------------------------------------
def parse_transactions(text):
    records = []

    # Split by UTR (strongest anchor)
    chunks = re.split(r'UTR\s*No\.?\s*(?:\:)?\s*', text, flags=re.IGNORECASE)

    for chunk in chunks[1:]:
        try:
            utr = re.match(r'(\S+)', chunk).group(1)

            tid = TID_RE.search(chunk)
            tid = tid.group(1) if tid else ""

            amt = AMOUNT_RE.search(chunk)
            txn_type = amt.group(1).title() if amt else ""
            amount = amt.group(2).replace(",", "") if amt else ""

            date = DATE_RE.search(chunk)
            date = date.group(0) if date else ""

            time = TIME_RE.search(chunk)
            time = time.group(0) if time else ""

            details = DETAILS_RE.search(chunk)
            details = details.group(2).strip() if details else ""

            records.append({
                "Date & Time": f"{date} {time}".strip(),
                "Transaction Details": details,
                "Transaction ID": tid,
                "UTR No": utr,
                "Type": txn_type,
                "Amount": amount
            })
        except Exception:
            continue

    return pd.DataFrame(records)


# -------------------------------------------------
# Streamlit UI
# -------------------------------------------------
st.set_page_config(page_title="PhonePe PDF → CSV / Excel", page_icon="💳")
st.title("💳 PhonePe PDF → CSV / Excel Converter")

st.markdown("""
### ℹ️ How to use
1. Upload your **PhonePe PDF statement**
2. Enter password **only if prompted**
3. Click **Convert**
4. Download **CSV / Excel**

✅ Supports **all known PhonePe PDF formats**  
🔐 Files are processed locally and never stored
""")

uploaded = st.file_uploader("📂 Upload PhonePe PDF", type="pdf")
password = st.text_input("🔑 PDF Password (only if required)", type="password")
fmt = st.radio("📄 Output format", ["csv", "excel"])

if uploaded and st.button("🚀 Convert"):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.getbuffer())
            pdf_path = tmp.name

        pdf_path, text = unlock_pdf_if_needed(pdf_path, password)

        df = parse_transactions(text)

        if df.empty:
            st.error("❌ No transactions found.")
        else:
            st.success(f"✅ Parsed {len(df)} transactions")
            st.dataframe(df.head(10), use_container_width=True)

            if fmt == "csv":
                st.download_button(
                    "⬇️ Download CSV",
                    df.to_csv(index=False).encode("utf-8"),
                    "phonepe_transactions.csv",
                    "text/csv"
                )
            else:
                tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                df.to_excel(tmp_out.name, index=False)
                with open(tmp_out.name, "rb") as f:
                    st.download_button(
                        "⬇️ Download Excel",
                        f.read(),
                        "phonepe_transactions.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                os.remove(tmp_out.name)

        os.remove(pdf_path)

    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
