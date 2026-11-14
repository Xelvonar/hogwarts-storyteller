STORYTELLER_SYSTEM_INSTRUCTION = """
You are the Co-Director and Chronicler for an interactive fiction retelling of Harry Potter: Year Two (Chamber of Secrets), written in third-person limited POV tightly anchored to Mark Peabody (Hufflepuff).

### 1. TONE, VOICE & 12-YEAR-OLD REALISM
- **Early Rowling Boarding-School Cadence:** Grounded, sensory, wry, and unpretentious.
- **Anti-Caricature Rule:** Keep 80% of dialogue ordinary, practical, and un-quirky. Characters have their own chores, homework panics, and summer routines. Use Default Quirks sparingly (at most once per scene) and deploy Pressure Quirks ONLY under genuine danger, conflict, or strain.
- **Anti-Stage-Play Dialogue Filter:** Never write 12-year-olds giving polished speeches. Use clipped fragments, trailing thoughts, interruptions, clumsy bluffs, and immediate physical distractions (chewing toast, dropping a quill, kicking a table leg).
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

TURN_DIFF_SCHEMA = {
    "type": "object",
    "properties": {
        "salience": {
            "type": "integer",
            "description": "1: Fleeting micro-beat (intra-scene only), 2: Minor scene detail (RAM only), 3: Seasonal watershed/bonding, 4: Major year-long event, 5: Permanent trauma/keystone."
        },
        "new_date": {
            "type": "string",
            "description": "Updated in-universe date/period ONLY if time explicitly advanced; otherwise empty string."
        },
        "new_location": {
            "type": "string",
            "description": "Updated location ONLY if Mark moved to a new place; otherwise empty string."
        },
        "transient_facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 short micro-facts from this turn relevant to the immediate scene."
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
    "required": ["salience", "new_date", "new_location", "transient_facts", "knowledge_updates", "attitude_deltas", "character_location_updates"]
}

SCENE_WRAP_SCHEMA = {
    "type": "object",
    "properties": {
        "worth_remembering": {
            "type": "boolean",
            "description": "True ONLY if the completed scene as a whole reached Salience 3, 4, or 5 (seasonal milestone, meaningful bonding/conflict, secret learned, or major event). False for routine slice-of-life scenes."
        },
        "salience": {
            "type": "integer",
            "description": "3: Seasonal memory (~2 months), 4: Year-long memory (1 year), 5: Permanent keystone (never deleted). Set to 1 or 2 if worth_remembering is false."
        },
        "characters": {
            "type": "string",
            "description": "Comma-separated names of characters featured in or directly affected by the scene."
        },
        "interaction_summary": {
            "type": "string",
            "description": "1 concise sentence summarizing the overall scene context."
        },
        "memory": {
            "type": "string",
            "description": "1-2 concise sentences capturing the lasting emotional or factual anchor from this scene."
        }
    },
    "required": ["worth_remembering", "salience", "characters", "interaction_summary", "memory"]
}
