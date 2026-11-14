import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.title("🔧 Connection Smoke Test")

# 1. Check if Secrets loaded properly
if "gcp_service_account" not in st.secrets:
    st.error("❌ Could not find [gcp_service_account] in Streamlit Secrets. Check spelling and formatting.")
    st.stop()
else:
    st.success("✅ Found [gcp_service_account] in Secrets!")

# 2. Try authenticating and opening the Mark Peabody Information Tracker
try:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/documents"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    gc = gspread.authorize(creds)
    
    SHEET_ID = "1qk9mmxj5pFzY39eyyOS6mkYItgldn8rhpeP0zB8uzec"
    spreadsheet = gc.open_by_key(SHEET_ID)
    
    tab_names = [ws.title for ws in spreadsheet.worksheets()]
    st.success(f"🎉 Connected to '{spreadsheet.title}'!")
    st.write("**Tabs found:**", tab_names)

except Exception as e:
    st.error(f"❌ Connection failed: {e}")
