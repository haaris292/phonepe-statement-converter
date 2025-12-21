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
# Regex patterns (robust)
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
def try_extract_text(pdf_path: str) -> str | None:
    """
    Attempt to extract text without worrying about encryption.
    Returns text if successful, else None.
    """
    try:
        text = ""
        with pdfplumber.open(pdf_path, laparams={"detect_vertical": False}) as pdf:
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=2, y_tolerance=2)
                if t:
                    text += "\n" + t
        return text if text.strip() else None
    except Exception:
        return None


def unlock_pdf_if_needed(pdf_path: str, password: str | None) -> str:
    """
    Unlock PDF ONLY if text extraction fails.
    """
    # First attempt: extract directly
    direct_text = try_extract_text(pdf_path)
    if direct_text:
        return pdf_path

    # If extraction failed, try decrypting
    reader = PdfReader(pdf_path)

    if not reader.is_encrypted:
        raise ValueError("PDF could not be read, but is not encrypted.")

    if not password:
        raise ValueError("PDF appears restricted. Please provide the password.")

    if reader.decrypt(password) == 0:
        raise ValueError("Incorrect PDF password.")

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    with open(tmp.name, "wb") as f:
        writer.write(f)

    return tmp.name


# -------------------------------------------------
# Parser (bulletproof)
# -------------------------------------------------
def parse_transactions_from_text(text: str) -> pd.DataFrame:
    records = []
    chunks = UTR_SPLIT_RE.split(text)

    for chunk in chunks[1:]:
        try:
            utr = re.match(r'(\S+)', chunk).group(1)

            tid_match = TID_RE.search(chunk)
            tid = tid_match.group(1) if tid_match else ""

            amt_match = AMOUNT_RE.search(chunk)
            txn_type = amt_match.group(1).title() if amt_match else ""
            amount = amt_match.group(2).replace(",", "") if amt_match else ""

            date_match = DATE_RE.search(chunk)
            date = date_match.group(0) if date_match else ""

            time_match = TIME_RE.search(chunk)
            time = time_match.group(0) if time_match else ""

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

🔐 Your data is processed in memory and never stored.
""")

uploaded = st.file_uploader("📂 Upload PhonePe PDF", type="pdf")
password = st.text_input("🔑 PDF Password (only if needed)", type="password")
fmt = st.radio("📄 Output format", ["csv", "excel"])

if uploaded and st.button("🚀 Convert"):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.getbuffer())
            pdf_path = tmp.name

        # Unlock only if required
        pdf_path = unlock_pdf_if_needed(pdf_path, password if password else None)

        text = try_extract_text(pdf_path)
        if not text:
            raise ValueError("Unable to extract text from PDF.")

        df = parse_transactions_from_text(text)

        if df.empty:
            st.error("❌ No transactions found. This PDF format is not supported.")
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
