import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SHEET_ID = "1qk9mmxj5pFzY39eyyOS6mkYItgldn8rhpeP0zB8uzec"
DOC_ID = "1gjNoEoIxCcDcpWnRAGC44gobRoMji8UNxCFz3xT3rx4"

@st.cache_resource
def init_google_clients():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/documents"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SHEET_ID)
    docs_service = build("docs", "v1", credentials=creds)
    return spreadsheet, docs_service

def load_world_database(sh):
    """Fetches all 8 tabs from Mark Peabody Information Tracker into RAM."""
    ss_rows = sh.worksheet("Session State").get_all_values()
    session_meta = {}
    for row in ss_rows:
        if len(row) >= 2 and row[0].strip():
            session_meta[row[0].strip()] = row[1].strip()

    return {
        "session_meta": session_meta,
        "characters": sh.worksheet("Characters").get_all_records(),
        "character_info": sh.worksheet("Character Information").get_all_records(),
        "attitudes": sh.worksheet("Attitude Tracker").get_all_records(),
        "intent_magic": sh.worksheet("Intent Magic Information").get_all_records(),
        "key_memories": sh.worksheet("Key Memories").get_all_records(),
        "story_arcs": sh.worksheet("Story Arcs").get_all_records(),
        "knowledge": sh.worksheet("Knowledge").get_all_records(),
    }

def append_to_living_novel_doc(docs_service, user_prompt: str, story_prose: str):
    """History 1: Appends raw player prompt and prose verbatim to Google Doc (output-only sink)."""
    try:
        doc = docs_service.documents().get(documentId=DOC_ID).execute()
        end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1
        end_index = max(1, end_index)

        formatted_block = f"\n\n> Mark: {user_prompt}\n\n{story_prose}\n"
        requests = [{"insertText": {"location": {"index": end_index}, "text": formatted_block}}]
        docs_service.documents().batchUpdate(documentId=DOC_ID, body={"requests": requests}).execute()
    except Exception as e:
        st.warning(f"Note: Could not append to Narrative History Doc ({e})")

def append_key_memory(sh, db: dict, date_str: str, characters: str, salience: int, summary: str, memory: str):
    """Writes a Salience 3-5 memory to the Key Memories tab and updates local RAM."""
    km_ws = sh.worksheet("Key Memories")
    new_row = [date_str, characters, salience, summary, memory]
    km_ws.append_row(new_row)
    db["key_memories"].append({
        "Date": date_str,
        "Characters": characters,
        "Salience": salience,
        "Interaction Summary": summary,
        "Memory": memory
    })

def reset_scene_turn_in_sheet(sh, meta: dict):
    """Resets Scene Turn to 1 in Session State tab when starting a new scene."""
    meta["Scene Turn"] = "1"
    sh.worksheet("Session State").update(values=[[k, v] for k, v in meta.items()], range_name="A1")

def commit_turn_diff(sh, db: dict, diff: dict) -> str:
    """Applies per-turn state updates (Session State, Attitudes, Knowledge, Locations)."""
    audit_notes = []

    # 1. Update Session State
    meta = db["session_meta"]
    current_date = diff["new_date"].strip() if diff.get("new_date", "").strip() else meta.get("Date", "Early July 1992")
    current_loc = diff["new_location"].strip() if diff.get("new_location", "").strip() else meta.get("Location", "Surrey")
    try:
        next_turn = int(meta.get("Scene Turn", 1)) + 1
    except ValueError:
        next_turn = 2

    meta["Date"] = current_date
    meta["Location"] = current_loc
    meta["Scene Turn"] = str(next_turn)

    sh.worksheet("Session State").update(values=[[k, v] for k, v in meta.items()], range_name="A1")
    audit_notes.append(f"Session State → {current_date} | {current_loc} | Turn {next_turn}")

    # 2. Store transient micro-facts in RAM
    new_facts = diff.get("transient_facts", [])
    if new_facts:
        st.session_state.transient_facts.extend(new_facts)
        st.session_state.transient_facts = st.session_state.transient_facts[-8:]

    salience = diff.get("salience", 1)
    audit_notes.append(f"Turn Salience: {salience}")

    # 3. Elastic Decay + Attitude Deltas
    deltas = diff.get("attitude_deltas", [])
    delta_lookup = {(d["character"], d["value_toward"], d["domain"]): d["delta"] for d in deltas}
    att_changed = False
    decay_rate = 0.15

    for row in db["attitudes"]:
        try:
            lt_val = float(row["Long Term Value"])
            cur_val = float(row["Current Value"])
        except (ValueError, TypeError):
            continue

        key = (row["Character"], row["Value Toward"], row["Domain"])
        shift = delta_lookup.get(key, 0.0)

        updated_val = round(max(0.0, min(1.0, cur_val + decay_rate * (lt_val - cur_val) + shift)), 2)

        if salience == 5 and shift != 0.0:
            lt_val = round(max(0.0, min(1.0, lt_val + (shift * 0.5))), 2)
            row["Long Term Value"] = lt_val

        if updated_val != cur_val or shift != 0.0:
            row["Current Value"] = updated_val
            att_changed = True
            if shift != 0.0:
                audit_notes.append(f"Attitude: {row['Character']}→{row['Value Toward']} ({row['Domain']} {shift:+.2f})")

    if att_changed:
        headers = ["Character", "Value Toward", "Domain", "Long Term Value", "Current Value"]
        matrix = [headers] + [[r[h] for h in headers] for r in db["attitudes"]]
        sh.worksheet("Attitude Tracker").update(values=matrix, range_name="A1")

    # 4. Knowledge Updates
    k_updates = diff.get("knowledge_updates", [])
    if k_updates:
        for ku in k_updates:
            if ku["character"].upper() == "PUBLIC":
                continue
            matched = False
            for row in db["knowledge"]:
                if row["Character"] == ku["character"] and row["Fact/Secret"] == ku["fact_secret"]:
                    row["Knowledge State"] = ku["new_knowledge_state"]
                    row["Last Updated"] = current_date
                    matched = True
                    break
            if not matched:
                db["knowledge"].append({
                    "Character": ku["character"],
                    "Fact/Secret": ku["fact_secret"],
                    "Knowledge State": ku["new_knowledge_state"],
                    "Last Updated": current_date
                })
            audit_notes.append(f"Knowledge: {ku['character']} ({ku['fact_secret']})")

        k_headers = ["Character", "Fact/Secret", "Knowledge State", "Last Updated"]
        k_matrix = [k_headers] + [[r[h] for h in k_headers] for r in db["knowledge"]]
        sh.worksheet("Knowledge").update(values=k_matrix, range_name="A1")

    # 5. Character Location / Activity Updates
    loc_updates = diff.get("character_location_updates", [])
    if loc_updates:
        for lu in loc_updates:
            for row in db["characters"]:
                if row["Character Name"] == lu["character_name"]:
                    if lu.get("new_location"):
                        row["Current Location"] = lu["new_location"]
                    if lu.get("new_activity"):
                        row["Current Off-Screen Activity"] = lu["new_activity"]
                    audit_notes.append(f"Moved {lu['character_name']} → {lu['new_location']}")
        c_headers = list(db["characters"][0].keys())
        c_matrix = [c_headers] + [[r[h] for h in c_headers] for r in db["characters"]]
        sh.worksheet("Characters").update(values=c_matrix, range_name="A1")

    return " | ".join(audit_notes)
