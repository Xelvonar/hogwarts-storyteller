import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="Mark Peabody: Year Two", page_icon="🪄", layout="centered")

st.title("Mark Peabody: Year Two")
st.caption("Interactive Boarding School Storyteller Engine")

# Fetch API key securely from dashboard secrets
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error("Missing GEMINI_API_KEY. Please configure it in your Streamlit secrets settings.")
    st.stop()

client = genai.Client(api_key=api_key)

# Permanent System Instruction baked into every call
SYSTEM_INSTRUCTION = """
You are the Co-Director and Narrator for an interactive fiction retelling of Harry Potter: Year Two (Chamber of Secrets), centered on Mark Peabody (Hufflepuff).

1. Perspective: Strict Third-Person Limited (Free Indirect Discourse) tethered behind Mark Peabody. Mark is a 12-year-old child: no adult psychological terms, no omniscient knowledge.
2. Magic Recoil: Intent magic demands biological costs (epistaxis, tremors, leaden limbs, radial numbness, cold skin). His 6.5-inch rigid maple wand is a grounding rod, not a paintbrush; excessive charge causes heat, weeping sap, or grain vibration.
3. Cadence: Early J.K. Rowling style—dry British humor, sensory castle atmosphere (damp stone, ozone, coal smoke), authentic schoolboy dialogue.
4. Social Noise: Mark is not the center of the universe. Friends have their own chores, homework panics, and distractions.
5. Agency: Advance 3 to 4 paragraphs per turn. Never resolve a crisis or consequence for Mark; pause to let the player decide.
6. Turn Structure:
   - Header: ### [Early/Mid/Late Month 1992 | Turn X]
   - Footer: End with three one-sentence options prefixed by 'Suggested next steps:'
"""

# Initialize persistent chat session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render previous transcript
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Player input bar
user_prompt = st.chat_input("What does Mark do?")

if user_prompt:
    # 1. Display player's action
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    # 2. Reconstruct context from the last 8 turns (prevents memory bloat while preserving recency)
    recent_history = [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part.from_text(text=m["content"])]
        )
        for m in st.session_state.messages[-8:]
    ]

    # 3. Call Gemini
    with st.chat_message("assistant"):
        with st.spinner("The castle stirs..."):
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=recent_history,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.8,
                )
            )
            st.markdown(response.text)
            st.session_state.messages.append({"role": "assistant", "content": response.text})
