import json
import time
import streamlit as st
from google import genai
from google.genai import types
from prompts import STORYTELLER_SYSTEM_INSTRUCTION, TURN_DIFF_SCHEMA, SCENE_WRAP_SCHEMA

PRIMARY_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-pro"]

@st.cache_resource
def init_gemini_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

def call_gemini(prompt_contents: str, system_instruction: str, temperature: float, json_schema=None) -> str:
    client = init_gemini_client()
    last_error = None
    for model_name in [PRIMARY_MODEL] + FALLBACK_MODELS:
        try:
            config_args = {
                "system_instruction": system_instruction,
                "temperature": temperature,
            }
            if json_schema:
                config_args["response_mime_type"] = "application/json"
                config_args["response_schema"] = json_schema

            response = client.models.generate_content(
                model=model_name,
                contents=prompt_contents,
                config=types.GenerateContentConfig(**config_args)
            )
            return response.text
        except Exception as e:
            last_error = e
            time.sleep(1)
    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

def generate_story_turn(world_snapshot: dict, scene_turns: list[dict]) -> str:
    """Pass 1: Generates narrative prose using the full world snapshot + active scene transcript."""
    transcript = "\n\n".join(
        [f"{m['role'].upper()}: {m['content']}" for m in scene_turns]
    )
    prompt = f"""
### COMPLETE WORLD DATABASE SNAPSHOT (REFERENCE ONLY)
{json.dumps(world_snapshot, indent=2)}

### CURRENT SCENE TRANSCRIPT (HISTORY 2 — ACTIVE SCENE MEMORY)
{transcript}

### INSTRUCTION
Write the next narrative response from Mark Peabody's third-person limited perspective.
"""
    return call_gemini(
        prompt_contents=prompt,
        system_instruction=STORYTELLER_SYSTEM_INSTRUCTION,
        temperature=0.8
    )

def audit_turn_diff(world_snapshot: dict, user_input: str, story_prose: str) -> dict:
    """Pass 2A: Extracts immediate per-turn state diffs (date, location, attitudes, knowledge, micro-facts)."""
    diff_system = """
You are a cold, conservative database auditor for an interactive story. Do NOT write fiction.
Compare the newly generated turn against the pre-turn world database and output ONLY verified changes in strict JSON.
- Extract 1-3 short `transient_facts` for immediate intra-scene continuity.
- Only add `knowledge_updates` if a character directly learned or deduced a specific Fact/Secret in this turn. Never modify PUBLIC rows.
- Only add `attitude_deltas` if a notable interpersonal shift occurred.
"""
    prompt = f"""
PRE-TURN WORLD SNAPSHOT:
{json.dumps(world_snapshot, indent=2)}

PLAYER ACTION:
{user_input}

NEWLY GENERATED PROSE:
{story_prose}
"""
    raw = call_gemini(prompt, diff_system, temperature=0.1, json_schema=TURN_DIFF_SCHEMA)
    return json.loads(raw)

def evaluate_completed_scene(scene_turns: list[dict], existing_memories: list[dict]) -> dict:
    """Pass 2B: Runs when a scene ends to decide if the scene warrants a Salience 3-5 Key Memory."""
    transcript = "\n\n".join([f"{m['role'].upper()}: {m['content']}" for m in scene_turns])
    wrap_system = """
You are a narrative archivist reviewing a completed scene from an interactive story.
Decide whether the scene as a whole is worth saving to the permanent 'Key Memories' table (Salience 3, 4, or 5):
- Salience 1-2 (worth_remembering = false): Routine daily chatter, breakfast letters, ordinary chores, or minor banter.
- Salience 3 (worth_remembering = true): Meaningful seasonal bonding, significant argument, or notable milestone (~2 months retention).
- Salience 4 (worth_remembering = true): Major year-long event or significant secret shared (1 year retention).
- Salience 5 (worth_remembering = true): Permanent watershed crisis, trauma, or life-altering vow (never deleted).
Do not duplicate events already captured in `existing_memories`.
"""
    prompt = f"""
EXISTING KEY MEMORIES (DO NOT DUPLICATE):
{json.dumps(existing_memories[-15:], indent=2)}

COMPLETED SCENE TRANSCRIPT:
{transcript}
"""
    raw = call_gemini(prompt, wrap_system, temperature=0.1, json_schema=SCENE_WRAP_SCHEMA)
    return json.loads(raw)
