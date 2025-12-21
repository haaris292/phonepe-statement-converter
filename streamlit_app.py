# streamlit_app.py
# pip install streamlit pdfplumber pandas openpyxl PyPDF2

import streamlit as st
import pandas as pd
import tempfile
import pdfplumber
from PyPDF2 import PdfReader, PdfWriter
import re
import os
import unicodedata

# -----------------------------
# Regex patterns
# -----------------------------
DATE_RE = re.compile(r'[A-Za-z]{3}\s+\d{1,2},\s*\d{4}')
TIME_RE = re.compile(r'\d{1,2}[:￾]\d{2}\s*(am|pm)', re.IGNORECASE)
AMOUNT_RE = re.compile(r'(DEBIT|CREDIT)\s*[₹]?\s*([\d,]+)', re.IGNORECASE)
TID_RE = re.compile(r'Transaction ID\s*(?:\:)?\s*(\S+)', re.IGNORECASE)
DETAILS_RE = re.compile(
    r'(Paid to|Received from)\s+(.+?)\s+(DEBIT|CREDIT)',
    re.IGNORECASE | re.DOTALL
)

# -----------------------------
# Category rules
# -----------------------------
CATEGORY_RULES = {
    "Groceries": ["dudh", "milk", "kirana", "store", "mart", "general"],
    "Medical": ["medical", "pharma", "hospital", "clinic", "eye", "lab"],
    "Food & Dining": ["hotel", "restaurant", "dosa", "biryani", "bakery"],
    "Fuel": ["petroleum", "fuel", "hp", "io", "bp"],
    "Shopping": ["collection", "fashion", "dress"],
    "Utilities": ["electric", "water", "gas"],
}

# -----------------------------
# Helpers
# -----------------------------
def sanitize_for_excel(val):
    if not isinstance(val, str):
        return val
    val = unicodedata.normalize("NFKD", val)
    val = "".join(ch for ch in val if ord(ch) >= 32)
    return val.strip()


def categorize(details):
    text = details.lower()
    for cat, keywords in CATEGORY_RULES.items():
        if any(k in text for k in keywords):
            return cat
    return "Others"


def extract_text(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text(x_tolerance=2, y_tolerance=2)
            if t:
                text += "\n" + t.replace("￾", ":")
    return text


def parse_transactions(text):
    records = []
    chunks = re.split(r'UTR\s*No\.?\s*(?:\:)?\s*', text, flags=re.IGNORECASE)

    for chunk in chunks[1:]:
        try:
            utr = re.match(r'(\S+)', chunk).group(1)

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
                "Category": categorize(details)
            })
        except Exception:
            continue

    return pd.DataFrame(records)


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="PhonePe Analyzer", page_icon="💳")
st.title("💳 PhonePe Statement Analyzer")

st.markdown("""
### ℹ️ What this app does
- Converts PhonePe PDF → CSV / Excel
- Automatically categorizes expenses
- Shows where your money is going 📊
""")

uploaded = st.file_uploader("📂 Upload PhonePe PDF", type="pdf")
fmt = st.radio("📄 Download format", ["csv", "excel"])

if uploaded and st.button("🚀 Analyze"):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded.getbuffer())
        path = tmp.name

    text = extract_text(path)
    df = parse_transactions(text)
    os.remove(path)

    if df.empty:
        st.error("No transactions found.")
    else:
        st.success(f"Parsed {len(df)} transactions")

        # -----------------------------
        # Overview
        # -----------------------------
        total_debit = df[df["Type"] == "Debit"]["Amount"].sum()
        total_credit = df[df["Type"] == "Credit"]["Amount"].sum()

        col1, col2 = st.columns(2)
        col1.metric("Total Spent (Debit)", f"₹{total_debit:,.0f}")
        col2.metric("Total Received (Credit)", f"₹{total_credit:,.0f}")

        # -----------------------------
        # Category analysis
        # -----------------------------
        st.subheader("📊 Spending by Category")
        cat_df = (
            df[df["Type"] == "Debit"]
            .groupby("Category")["Amount"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        st.bar_chart(cat_df.set_index("Category"))

        # -----------------------------
        # Top merchants
        # -----------------------------
        st.subheader("🏪 Top Spending Merchants")
        top_merchants = (
            df[df["Type"] == "Debit"]
            .groupby("Transaction Details")["Amount"]
            .sum()
            .sort_values(ascending=False)
            .head(10)
        )
        st.table(top_merchants)

        # -----------------------------
        # Raw data
        # -----------------------------
        st.subheader("📄 All Transactions")
        st.dataframe(df, use_container_width=True)

        # -----------------------------
        # Downloads
        # -----------------------------
        if fmt == "csv":
            st.download_button(
                "⬇️ Download CSV",
                df.to_csv(index=False).encode("utf-8"),
                "phonepe_analysis.csv",
                "text/csv"
            )
        else:
            df_excel = df.applymap(sanitize_for_excel)
            tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            df_excel.to_excel(tmp_out.name, index=False)
            with open(tmp_out.name, "rb") as f:
                st.download_button(
                    "⬇️ Download Excel",
                    f.read(),
                    "phonepe_analysis.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            os.remove(tmp_out.name)
