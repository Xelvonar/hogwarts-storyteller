import json
import time
import streamlit as st
from google import genai
from google.genai import types
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==============================================================================
# 1. CONFIGURATION & CONSTANTS
# ==============================================================================
st.set_page_config(page_title="Hogwarts Storyteller: Mark Peabody", page_icon="🪄", layout="centered")

SHEET_ID = "1qk9mmxj5pFzY39eyyOS6mkYItgldn8rhpeP0zB8uzec"
DOC_ID = "1gjNoEoIxCcDcpWnRAGC44gobRoMji8UNxCFz3xT3rx4"

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-pro"]

# ==============================================================================
# 2. AUTHENTICATION & GOOGLE WORKSPACE CONNECTIONS (CACHED)
# ==============================================================================
@st.cache_resource
def init_clients():
    gemini_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
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
    return gemini_client, spreadsheet, docs_service

gemini_client, sh, docs_service = init_clients()

# ==============================================================================
# 3. DATABASE LOADING & CACHING
# ==============================================================================
def load_world_database():
    """Fetches all 8 tabs from Mark Peabody Information Tracker into RAM."""
    ss_rows = sh.worksheet("Session State").get_all_values()
    session_meta = {}
    for row in ss_rows:
        if len(row) >= 2 and row[0].strip():
            session_meta[row[0].strip()] = row[1].strip()

    db = {
        "session_meta": session_meta,
        "characters": sh.worksheet("Characters").get_all_records(),
        "character_info": sh.worksheet("Character Information").get_all_records(),
        "attitudes": sh.worksheet("Attitude Tracker").get_all_records(),
        "intent_magic": sh.worksheet("Intent Magic Information").get_all_records(),
        "key_memories": sh.worksheet("Key Memories").get_all_records(),
        "story_arcs": sh.worksheet("Story Arcs").get_all_records(),
        "knowledge": sh.worksheet("Knowledge").get_all_records(),
    }
    return db

if "world_db" not in st.session_state:
    with st.spinner("Loading Mark Peabody Information Tracker..."):
        st.session_state.world_db = load_world_database()

if "scene_turns" not in st.session_state:
    st.session_state.scene_turns = []

if "transient_facts" not in st.session_state:
    st.session_state.transient_facts = []

if "last_audit_log" not in st.session_state:
    st.session_state.last_audit_log = None

# ==============================================================================
# 4. SYSTEM PROMPTS & PASS 2 SCHEMA
# ==============================================================================
STORYTELLER_SYSTEM_INSTRUCTION = """
You are the Co-Director and Chronicler for an interactive fiction retelling of Harry Potter: Year Two (Chamber of Secrets), written in third-person limited POV tightly anchored to Mark Peabody (Hufflepuff).

### 1. TONE, VOICE & CHARACTER REALISM
- **Early Rowling Boarding-School Cadence:** Grounded, sensory, wry, and unpretentious.
- **12-Year-Old Realism (Anti-Caricature Rule):** Keep 80% of dialogue ordinary, practical, and un-quirky. Characters have their own chores, homework panics, and summer routines. Do NOT turn friends into hovering "mother hens" or reduce them to repetitive catchphrases.
- **Mark's Voice & Lens:** Plain working-class Surrey cadence. Evaluates strange events through Muggle mechanical/repair logic (faulty pipes, pressure, drafts) rather than magical deduction. Hates being coddled; shoves hands into pockets or retreats into stubborn silence under pressure.

### 2. EPISTEMIC FIREWALL (STRICT)
- You are receiving the complete world database for reference. **Strictly ignore any character, memory, or subplot not physically present or directly raised in the immediate scene.**
- **Knowledge Lookup Rules:**
  1. Check if a character has a specific row for a Fact/Secret in `knowledge`. If so, honor that exact Knowledge State.
  2. If no specific row exists, check if a `PUBLIC` row exists for that Fact/Secret and use that cover story.
  3. If neither exists, the character's knowledge is **NONE** (completely ignorant).
- **Zero Omniscience Creep:** Mark and his peers have ZERO foreknowledge of canon mysteries (Chamber of Secrets, Basilisk, pipes, Tom Riddle's diary, Horcruxes). Never hint at canon spoilers in Mark's internal thoughts.

### 3. VISCERAL / INTENT MAGIC MECHANICS
- Governed strictly by the `intent_magic` table (Power Levels 1–4) and the Dumbledore/Snape/Vance summer prohibition.
- Translate physical recoil into grounded 12-year-old sensory details (fingers feeling like cold suet, hot copper taste of a nosebleed, dull ache at the base of the skull, 6.5" rigid maple wand growing hot or vibrating) rather than clinical jargon.

### 4. OUTPUT FORMAT
Start every response with a clean header line:
`**[Date] | [Location] | Scene Turn [N]**`

Write 2–4 rich, atmospheric paragraphs of story prose advancing the scene and pausing naturally for Mark's next choice or reply. Do NOT output JSON, meta-commentary, or bulleted "what do you do next?" menus unless requested.
"""

DIFF_SCHEMA = {
    "type": "object",
    "properties": {
        "salience": {
            "type": "integer",
            "description": "1: Fleeting micro-beat (intra-scene only), 2: Minor scene detail (RAM only), 3: Seasonal memory (kept ~2 months), 4: Year-long memory (kept 1 year), 5: Permanent keystone memory (never deleted)."
        },
        "new_date": {
            "type": "string",
            "description": "Updated in-universe date/period ONLY if time explicitly advanced in the scene; otherwise empty string."
        },
        "new_location": {
            "type": "string",
            "description": "Updated location ONLY if Mark moved to a new place; otherwise empty string."
        },
        "transient_facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 short, concrete micro-facts from this turn relevant to the immediate scene."
        },
        "key_memory": {
            "type": "object",
            "description": "Populate ONLY if salience >= 3. Otherwise leave fields empty.",
            "properties": {
                "should_record": {"type": "boolean"},
                "characters": {"type": "string"},
                "interaction_summary": {"type": "string"},
                "memory": {"type": "string"}
            },
            "required": ["should_record", "characters", "interaction_summary", "memory"]
        },
        "knowledge_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "character": {"type": "string"},
                    "fact_secret": {"type": "string"},
                    "new_knowledge_state": {"type": "string"}
                },
                "required": ["character", "fact_secret", "new_knowledge_state"]
            }
        },
        "attitude_deltas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "character": {"type": "string"},
                    "value_toward": {"type": "string"},
                    "domain": {"type": "string", "enum": ["Warmth", "Dominance", "Candor", "Harmony", "Reliability", "Discretion"]},
                    "delta": {"type": "number"}
                },
                "required": ["character", "value_toward", "domain", "delta"]
            }
        },
        "character_location_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "character_name": {"type": "string"},
                    "new_location": {"type": "string"},
                    "new_activity": {"type": "string"}
                },
                "required": ["character_name", "new_location", "new_activity"]
            }
        }
    },
    "required": ["salience", "new_date", "new_location", "transient_facts", "key_memory", "knowledge_updates", "attitude_deltas", "character_location_updates"]
}

# ==============================================================================
# 5. HELPER FUNCTIONS: LLM CALLS & GOOGLE WORKSPACE WRITES
# ==============================================================================
def call_gemini_with_fallback(prompt_contents: str, system_instruction: str, temperature: float, json_schema=None):
    models_to_try = [PRIMARY_MODEL] + FALLBACK_MODELS
    last_error = None
    for model_name in models_to_try:
        try:
            config_args = {
                "system_instruction": system_instruction,
                "temperature": temperature,
            }
            if json_schema:
                config_args["response_mime_type"] = "application/json"
                config_args["response_schema"] = json_schema

            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt_contents,
                config=types.GenerateContentConfig(**config_args)
            )
            return response.text
        except Exception as e:
            last_error = e
            time.sleep(1)
    raise RuntimeError(f"All models failed. Last error: {last_error}")

def append_to_narrative_doc(user_prompt: str, story_prose: str):
    """Appends the raw player action and generated story prose verbatim to Narrative History Doc."""
    try:
        doc = docs_service.documents().get(documentId=DOC_ID).execute()
        end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1
        end_index = max(1, end_index)

        formatted_block = f"\n\n> Mark: {user_prompt}\n\n{story_prose}\n"
        requests = [
            {
                "insertText": {
                    "location": {"index": end_index},
                    "text": formatted_block
                }
            }
        ]
        docs_service.documents().batchUpdate(documentId=DOC_ID, body={"requests": requests}).execute()
    except Exception as e:
        st.warning(f"Note: Could not append to Narrative History Doc ({e})")

def commit_state_updates(diff: dict):
    """Deterministically updates Session State, Key Memories, Attitudes, Knowledge, and Characters."""
    db = st.session_state.world_db
    audit_notes = []

    # 1. Update Session State (Date, Location, Scene Turn)
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

    ss_ws = sh.worksheet("Session State")
    ss_rows = [[k, v] for k, v in meta.items()]
    ss_ws.update(values=ss_rows, range_name="A1")
    audit_notes.append(f"Session State → {current_date} | {current_loc} | Turn {next_turn}")

    # 2. Salience 1-2: Store transient micro-facts in RAM only
    new_facts = diff.get("transient_facts", [])
    if new_facts:
        st.session_state.transient_facts.extend(new_facts)
        st.session_state.transient_facts = st.session_state.transient_facts[-8:]

    salience = diff.get("salience", 1)
    audit_notes.append(f"Salience: {salience}")

    # 3. Salience 3-5: Append to Key Memories tab
    km = diff.get("key_memory", {})
    if salience >= 3 and km.get("should_record") and km.get("memory"):
        km_ws = sh.worksheet("Key Memories")
        new_row = [
            current_date,
            km.get("characters", "Mark Peabody"),
            salience,
            km.get("interaction_summary", ""),
            km.get("memory", "")
        ]
        km_ws.append_row(new_row)
        db["key_memories"].append({
            "Date": current_date,
            "Characters": new_row[1],
            "Salience": salience,
            "Interaction Summary": new_row[3],
            "Memory": new_row[4]
        })
        audit_notes.append(f"Added Key Memory (Salience {salience})")

    # 4. Elastic Decay + Attitude Deltas on Attitude Tracker
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

        updated_val = cur_val + decay_rate * (lt_val - cur_val) + shift
        updated_val = round(max(0.0, min(1.0, updated_val)), 2)

        if salience == 5 and shift != 0.0:
            lt_val = round(max(0.0, min(1.0, lt_val + (shift * 0.5))), 2)
            row["Long Term Value"] = lt_val

        if updated_val != cur_val or shift != 0.0:
            row["Current Value"] = updated_val
            att_changed = True
            if shift != 0.0:
                audit_notes.append(f"Attitude: {row['Character']}→{row['Value Toward']} ({row['Domain']} {shift:+.2f})")

    if att_changed:
        att_ws = sh.worksheet("Attitude Tracker")
        headers = ["Character", "Value Toward", "Domain", "Long Term Value", "Current Value"]
        matrix = [headers] + [[r[h] for h in headers] for r in db["attitudes"]]
        att_ws.update(values=matrix, range_name="A1")

    # 5. Knowledge Updates
    k_updates = diff.get("knowledge_updates", [])
    if k_updates:
        k_ws = sh.worksheet("Knowledge")
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
                new_k = {
                    "Character": ku["character"],
                    "Fact/Secret": ku["fact_secret"],
                    "Knowledge State": ku["new_knowledge_state"],
                    "Last Updated": current_date
                }
                db["knowledge"].append(new_k)
            audit_notes.append(f"Knowledge: {ku['character']} ({ku['fact_secret']})")

        k_headers = ["Character", "Fact/Secret", "Knowledge State", "Last Updated"]
        k_matrix = [k_headers] + [[r[h] for h in k_headers] for r in db["knowledge"]]
        k_ws.update(values=k_matrix, range_name="A1")

    # 6. Character Location / Activity Updates
    loc_updates = diff.get("character_location_updates", [])
    if loc_updates:
        c_ws = sh.worksheet("Characters")
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
        c_ws.update(values=c_matrix, range_name="A1")

    return " | ".join(audit_notes)

# ==============================================================================
# 6. STREAMLIT UI & SIDEBAR CONTROLS
# ==============================================================================
db = st.session_state.world_db
meta = db["session_meta"]

with st.sidebar:
    st.header("🕰️ World State")
    st.write(f"**Date:** {meta.get('Date', 'Unknown')}")
    st.write(f"**Location:** {meta.get('Location', 'Unknown')}")
    st.write(f"**Scene Turn:** {meta.get('Scene Turn', 1)}")

    st.divider()
    if st.button("🎬 Start New Scene (Clear Micro-Facts)"):
        st.session_state.scene_turns = []
        st.session_state.transient_facts = []
        meta["Scene Turn"] = "1"
        sh.worksheet("Session State").update(values=[[k, v] for k, v in meta.items()], range_name="A1")
        st.success("Scene buffer cleared & Scene Turn reset to 1.")
        st.rerun()

    if st.button("🔄 Reload Google Sheet Data"):
        st.session_state.world_db = load_world_database()
        st.success("Reloaded latest spreadsheet edits!")
        st.rerun()

    if st.session_state.transient_facts:
        st.divider()
        st.subheader("📝 Current Scene Micro-Facts")
        for f in st.session_state.transient_facts:
            st.caption(f"• {f}")

st.title("🪄 Mark Peabody: Year Two")
st.caption(f"{meta.get('Date', '')} — {meta.get('Location', '')}")

for msg in st.session_state.scene_turns:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if st.session_state.last_audit_log:
    with st.expander("⚙️ Background State Audit (Last Turn)", expanded=False):
        st.caption(st.session_state.last_audit_log)

# ==============================================================================
# 7. MAIN TWO-PASS TURN LOOP
# ==============================================================================
if user_input := st.chat_input("What does Mark do or say?"):
    st.session_state.scene_turns.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    world_snapshot = {
        "session_state": db["session_meta"],
        "characters": db["characters"],
        "character_dossiers": db["character_info"],
        "attitude_tracker": db["attitudes"],
        "intent_magic_rules": db["intent_magic"],
        "key_memories": db["key_memories"],
        "story_arcs": db["story_arcs"],
        "knowledge_ledger": db["knowledge"],
        "current_scene_micro_facts": st.session_state.transient_facts,
    }

    recent_dialogue = "\n\n".join(
        [f"{m['role'].upper()}: {m['content']}" for m in st.session_state.scene_turns[-10:]]
    )

    pass1_prompt = f"""
### COMPLETE WORLD DATABASE SNAPSHOT (REFERENCE ONLY)
{json.dumps(world_snapshot, indent=2)}

### CURRENT SCENE TRANSCRIPT
{recent_dialogue}

### INSTRUCTION
Write the next narrative response from Mark Peabody's third-person limited perspective.
"""

    # --- PASS 1: THE STORYTELLER (temp = 0.8) ---
    with st.chat_message("assistant"):
        with st.spinner("Writing scene..."):
            story_prose = call_gemini_with_fallback(
                prompt_contents=pass1_prompt,
                system_instruction=STORYTELLER_SYSTEM_INSTRUCTION,
                temperature=0.8
            )
            st.markdown(story_prose)

    st.session_state.scene_turns.append({"role": "assistant", "content": story_prose})

    # --- COMMIT PROSE TO NARRATIVE HISTORY DOC ---
    append_to_narrative_doc(user_input, story_prose)

    # --- PASS 2: THE DIFF AUDITOR (temp = 0.1, Structured JSON) ---
    with st.spinner("Updating world state & memories..."):
        try:
            diff_system = """
You are a cold, conservative database auditor for an interactive story. Do NOT write fiction.
Compare the newly generated scene against the pre-turn world database and output ONLY verified changes in strict JSON.
- Salience 1: Fleeting micro-detail (passes in a few turns).
- Salience 2: Minor scene detail (stays in RAM for this scene only).
- Salience 3: Meaningful seasonal event/bonding (saved to Key Memories for ~2 months).
- Salience 4: Major year-long event (saved to Key Memories for 1 year).
- Salience 5: Permanent watershed/trauma (saved forever).
- Only record a `key_memory` if salience >= 3.
- Only add `knowledge_updates` if a character directly learned or deduced a specific Fact/Secret in this turn. Never modify PUBLIC rows.
"""
            diff_prompt = f"""
PRE-TURN WORLD SNAPSHOT:
{json.dumps(world_snapshot, indent=2)}

PLAYER ACTION:
{user_input}

NEWLY GENERATED SCENE PROSE:
{story_prose}
"""
            raw_diff = call_gemini_with_fallback(
                prompt_contents=diff_prompt,
                system_instruction=diff_system,
                temperature=0.1,
                json_schema=DIFF_SCHEMA
            )
            parsed_diff = json.loads(raw_diff)
            audit_summary = commit_state_updates(parsed_diff)
            st.session_state.last_audit_log = audit_summary
        except Exception as e:
            st.session_state.last_audit_log = f"⚠️ Sheet sync skipped due to error: {repr(e)}"

    st.rerun()
