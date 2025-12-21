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
# Regex patterns (structure-agnostic, robust)
# -------------------------------------------------
DATE_RE = re.compile(r'[A-Za-z]{3}\s+\d{1,2},\s*\d{4}')
TIME_RE = re.compile(r'\d{1,2}:\d{2}\s*(AM|PM)', re.IGNORECASE)
AMOUNT_RE = re.compile(r'(Debit|Credit)\s+INR\s+([\d,]+\.\d{2})', re.IGNORECASE)
TID_RE = re.compile(r'Transaction ID\s*:\s*(\S+)', re.IGNORECASE)
UTR_SPLIT_RE = re.compile(r'UTR No\s*:\s*', re.IGNORECASE)
DETAILS_RE = re.compile(
    r'(Paid to|Received from)\s+(.+?)(Debit|Credit)',
    re.IGNORECASE | re.DOTALL
)

# -------------------------------------------------
# PDF helpers
# -------------------------------------------------
def unlock_pdf(path: str, password: str | None) -> str:
    """
    Unlock PDF if encrypted. Returns path to unlocked PDF.
    """
    reader = PdfReader(path)
    if not reader.is_encrypted:
        return path

    if not password:
        raise ValueError("PDF is encrypted. Please provide the password.")

    if reader.decrypt(password) == 0:
        raise ValueError("Incorrect PDF password.")

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(tmp.name, "wb") as f:
        writer.write(f)

    return tmp.name


def extract_text_blocks(pdf_path: str) -> str:
    """
    Extract raw text blocks instead of lines.
    This survives broken fonts and merged text.
    """
    full_text = ""
    with pdfplumber.open(pdf_path, laparams={"detect_vertical": False}) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if text:
                full_text += "\n" + text
    return full_text


# -------------------------------------------------
# Core parser (bulletproof)
# -------------------------------------------------
def parse_transactions_from_text(text: str) -> pd.DataFrame:
    """
    Parse transactions using UTR as anchor.
    Ignores line breaks entirely.
    """
    records = []

    # Split using UTR (strongest boundary)
    chunks = UTR_SPLIT_RE.split(text)

    for chunk in chunks[1:]:
        try:
            # UTR
            utr_match = re.match(r'(\S+)', chunk)
            utr = utr_match.group(1) if utr_match else ""

            # Transaction ID
            tid_match = TID_RE.search(chunk)
            tid = tid_match.group(1) if tid_match else ""

            # Amount + type
            amt_match = AMOUNT_RE.search(chunk)
            txn_type = amt_match.group(1).title() if amt_match else ""
            amount = amt_match.group(2).replace(",", "") if amt_match else ""

            # Date
            date_match = DATE_RE.search(chunk)
            date = date_match.group(0) if date_match else ""

            # Time
            time_match = TIME_RE.search(chunk)
            time = time_match.group(0) if time_match else ""

            # Transaction details
            details_match = DETAILS_RE.search(chunk)
            details = details_match.group(2).strip() if details_match else ""

            records.append({
                "Date & Time": f"{date} {time}".strip(),
                "Transaction Details": details,
                "Transaction ID": tid,
                "UTR No": utr,
                "Type": txn_type,
                "Amount": amount
            })

        except Exception:
            # Skip malformed chunk safely
            continue

    return pd.DataFrame(records)


# -------------------------------------------------
# Streamlit UI
# -------------------------------------------------
st.set_page_config(
    page_title="PhonePe PDF → CSV / Excel",
    page_icon="💳",
    layout="centered"
)

st.title("💳 PhonePe PDF → CSV / Excel Converter")

st.markdown("""
### ℹ️ How to use
1. **Upload your PhonePe PDF statement**
2. Enter password **only if the PDF is locked**
3. Click **Convert**
4. Preview transactions
5. Download **CSV** or **Excel**

🔐 Your file is processed in memory and never stored.
""")

uploaded = st.file_uploader("📂 Upload PhonePe PDF", type="pdf")
password = st.text_input("🔑 PDF Password (leave empty if not encrypted)", type="password")
fmt = st.radio("📄 Output format", ["csv", "excel"])

if uploaded and st.button("🚀 Convert"):
    try:
        # Save uploaded PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.getbuffer())
            source_path = tmp.name

        # Unlock if needed
        source_path = unlock_pdf(source_path, password if password else None)

        # Extract raw text
        text = extract_text_blocks(source_path)

        # Parse
        df = parse_transactions_from_text(text)

        if df.empty:
            st.error("❌ No transactions found. This PDF format is not supported.")
        else:
            st.success(f"✅ Parsed {len(df)} transactions")
            st.dataframe(df.head(10), use_container_width=True)

            if fmt == "csv":
                st.download_button(
                    "⬇️ Download CSV",
                    data=df.to_csv(index=False).encode("utf-8"),
                    file_name="phonepe_transactions.csv",
                    mime="text/csv"
                )
            else:
                tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                df.to_excel(tmp_out.name, index=False)
                with open(tmp_out.name, "rb") as f:
                    st.download_button(
                        "⬇️ Download Excel",
                        data=f.read(),
                        file_name="phonepe_transactions.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                os.remove(tmp_out.name)

        os.remove(source_path)

    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
