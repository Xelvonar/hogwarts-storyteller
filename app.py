import streamlit as st
from workspace_io import (
    init_google_clients,
    load_world_database,
    append_to_living_novel_doc,
    append_key_memory,
    reset_scene_turn_in_sheet,
    commit_turn_diff,
)
from llm_engine import (
    generate_story_turn,
    audit_turn_diff,
    evaluate_completed_scene,
)

# ==============================================================================
# 1. PAGE SETUP & STATE INITIALIZATION
# ==============================================================================
st.set_page_config(page_title="Hogwarts Storyteller: Mark Peabody", page_icon="🪄", layout="centered")
sh, docs_service = init_google_clients()

if "world_db" not in st.session_state:
    with st.spinner("Loading Mark Peabody Information Tracker..."):
        st.session_state.world_db = load_world_database(sh)

# History 2: Active Scene Buffer (fed to LLM until scene ends, then wiped)
if "scene_turns" not in st.session_state:
    st.session_state.scene_turns = []

if "transient_facts" not in st.session_state:
    st.session_state.transient_facts = []

if "last_audit_log" not in st.session_state:
    st.session_state.last_audit_log = None

db = st.session_state.world_db
meta = db["session_meta"]

# ==============================================================================
# 2. SIDEBAR: WORLD STATE & SCENE TRANSITION CONTROLS
# ==============================================================================
with st.sidebar:
    st.header("🕰️ World State")
    st.write(f"**Date:** {meta.get('Date', 'Unknown')}")
    st.write(f"**Location:** {meta.get('Location', 'Unknown')}")
    st.write(f"**Scene Turn:** {meta.get('Scene Turn', 1)}")

    st.divider()
    if st.button("🎬 End Scene & Start New Scene"):
        if st.session_state.scene_turns:
            with st.spinner("Archiving scene & checking for Key Memories..."):
                try:
                    wrap = evaluate_completed_scene(st.session_state.scene_turns, db["key_memories"])
                    if wrap.get("worth_remembering") and wrap.get("memory"):
                        append_key_memory(
                            sh=sh,
                            db=db,
                            date_str=meta.get("Date", "Early July 1992"),
                            characters=wrap.get("characters", "Mark Peabody"),
                            salience=wrap.get("salience", 3),
                            summary=wrap.get("interaction_summary", ""),
                            memory=wrap.get("memory", "")
                        )
                        st.session_state.last_audit_log = f"📌 Scene Archived → Added Key Memory (Salience {wrap.get('salience')}): {wrap.get('memory')}"
                    else:
                        st.session_state.last_audit_log = "🎬 Scene Ended → Routine scene (no Key Memory added)."
                except Exception as e:
                    st.session_state.last_audit_log = f"⚠️ Scene wrap audit skipped: {repr(e)}"

        # Wipe History 2 (Active Scene Memory) & micro-facts for the fresh scene
        st.session_state.scene_turns = []
        st.session_state.transient_facts = []
        reset_scene_turn_in_sheet(sh, meta)
        st.rerun()

    if st.button("🔄 Reload Google Sheet Data"):
        st.session_state.world_db = load_world_database(sh)
        st.success("Reloaded latest spreadsheet edits!")
        st.rerun()

    if st.session_state.transient_facts:
        st.divider()
        st.subheader("📝 Current Scene Micro-Facts")
        for f in st.session_state.transient_facts:
            st.caption(f"• {f}")

# ==============================================================================
# 3. MAIN CHAT INTERFACE
# ==============================================================================
st.title("🪄 Mark Peabody: Year Two")
st.caption(f"{meta.get('Date', '')} — {meta.get('Location', '')}")

for msg in st.session_state.scene_turns:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if st.session_state.last_audit_log:
    with st.expander("⚙️ Background State Audit (Last Action)", expanded=False):
        st.caption(st.session_state.last_audit_log)

# ==============================================================================
# 4. TURN EXECUTION LOOP
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

    # Pass 1: Narrative Prose (reads full snapshot + History 2 active scene)
    with st.chat_message("assistant"):
        with st.spinner("Writing scene..."):
            story_prose = generate_story_turn(world_snapshot, st.session_state.scene_turns)
            st.markdown(story_prose)

    # Save to History 2 (RAM) & History 1 (Living Novel Google Doc)
    st.session_state.scene_turns.append({"role": "assistant", "content": story_prose})
    append_to_living_novel_doc(docs_service, user_input, story_prose)

    # Pass 2A: Per-turn state sync (Attitudes, Knowledge, Session State)
    with st.spinner("Updating world state..."):
        try:
            diff = audit_turn_diff(world_snapshot, user_input, story_prose)
            st.session_state.last_audit_log = commit_turn_diff(sh, db, diff)
        except Exception as e:
            st.session_state.last_audit_log = f"⚠️ Sheet sync skipped due to error: {repr(e)}"

    st.rerun()
