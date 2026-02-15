# streamlit_app.py
# Requirements:
# streamlit
# pdfplumber
# pandas
# openpyxl
# PyPDF2

import streamlit as st
import pandas as pd
import tempfile
import pdfplumber
from PyPDF2 import PdfReader, PdfWriter
import re
import os
import unicodedata

# -----------------------------
# Regex Patterns (Universal)
# -----------------------------
DATE_RE = re.compile(r'[A-Za-z]{3}\s+\d{1,2},\s*\d{4}')
TIME_RE = re.compile(r'\d{1,2}[:￾]\d{2}\s*(am|pm)', re.IGNORECASE)
AMOUNT_RE = re.compile(r'(DEBIT|CREDIT)\s*[₹]?\s*([\d,]+)', re.IGNORECASE)
DETAILS_RE = re.compile(
    r'(Paid to|Received from)\s+(.+?)\s+(DEBIT|CREDIT)',
    re.IGNORECASE | re.DOTALL
)

# -----------------------------
# Sanitization
# -----------------------------
def sanitize_text(text):
    if not isinstance(text, str):
        return text
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if ord(ch) >= 32)
    return text.strip()


# -----------------------------
# Safe PDF Extraction
# -----------------------------
def safe_extract_text(pdf_path):
    """
    Safely extract text from PDF.
    Prevents pdfminer crashes from breaking app.
    """
    try:
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                try:
                    page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                    if page_text:
                        page_text = page_text.replace("￾", ":")
                        text += "\n" + page_text
                except Exception:
                    continue
        return text
    except Exception:
        return None


# -----------------------------
# Transaction Parser
# -----------------------------
def parse_transactions(text):
    records = []

    # Split by UTR (strong anchor)
    chunks = re.split(r'UTR\s*No\.?\s*(?:\:)?\s*', text, flags=re.IGNORECASE)

    for chunk in chunks[1:]:
        try:
            utr_match = re.match(r'(\S+)', chunk)
            utr = utr_match.group(1) if utr_match else ""

            amt = AMOUNT_RE.search(chunk)
            txn_type = amt.group(1).title() if amt else ""
            amount = float(amt.group(2).replace(",", "")) if amt else 0.0

            date = DATE_RE.search(chunk)
            date = date.group(0) if date else ""

            time = TIME_RE.search(chunk)
            time = time.group(0) if time else ""

            details = DETAILS_RE.search(chunk)
            details = details.group(2).strip() if details else ""

            records.append({
                "Date & Time": f"{date} {time}".strip(),
                "Transaction Details": details,
                "Type": txn_type,
                "Amount": amount,
                "UTR": utr
            })
        except Exception:
            continue

    df = pd.DataFrame(records)
    if not df.empty:
        df["Transaction Details"] = df["Transaction Details"].apply(sanitize_text)
    return df


# -----------------------------
# Category Logic
# -----------------------------
CATEGORY_RULES = {
    "Groceries": ["dudh", "milk", "kirana", "mart", "store", "general"],
    "Medical": ["medical", "pharma", "hospital", "clinic", "lab", "eye"],
    "Food & Dining": ["hotel", "restaurant", "dosa", "bakery"],
    "Fuel": ["petroleum", "fuel"],
    "Shopping": ["collection", "fashion"],
}

def categorize(text):
    text = text.lower()
    for cat, words in CATEGORY_RULES.items():
        if any(w in text for w in words):
            return cat
    return "Others"


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="PhonePe Analyzer", page_icon="💳")
st.title("💳 PhonePe PDF Analyzer")

st.markdown("""
### What this app does
- Converts PhonePe PDF → CSV / Excel
- Categorizes your spending
- Shows spending insights
""")

uploaded = st.file_uploader("Upload PhonePe PDF", type="pdf")
download_format = st.radio("Download format", ["csv", "excel"])

if uploaded and st.button("Analyze"):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded.getbuffer())
            path = tmp.name

        text = safe_extract_text(path)
        os.remove(path)

        if not text:
            st.error("Could not extract text from this PDF.")
            st.stop()

        df = parse_transactions(text)

        if df.empty:
            st.error("No transactions found in this PDF.")
            st.stop()

        df["Category"] = df["Transaction Details"].apply(categorize)

        st.success(f"Parsed {len(df)} transactions")

        # Metrics
        total_spent = df[df["Type"] == "Debit"]["Amount"].sum()
        total_received = df[df["Type"] == "Credit"]["Amount"].sum()

        col1, col2 = st.columns(2)
        col1.metric("Total Spent", f"₹{total_spent:,.0f}")
        col2.metric("Total Received", f"₹{total_received:,.0f}")

        # Category Chart
        st.subheader("Spending by Category")
        cat_df = (
            df[df["Type"] == "Debit"]
            .groupby("Category")["Amount"]
            .sum()
            .sort_values(ascending=False)
        )
        st.bar_chart(cat_df)

        # Raw Table
        st.subheader("All Transactions")
        st.dataframe(df, use_container_width=True)

        # Downloads
        if download_format == "csv":
            st.download_button(
                "Download CSV",
                df.to_csv(index=False).encode("utf-8"),
                "phonepe_analysis.csv"
            )
        else:
            tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            df.to_excel(tmp_out.name, index=False)
            with open(tmp_out.name, "rb") as f:
                st.download_button(
                    "Download Excel",
                    f.read(),
                    "phonepe_analysis.xlsx"
                )
            os.remove(tmp_out.name)

    except Exception as e:
        st.error("Unexpected error occurred.")
