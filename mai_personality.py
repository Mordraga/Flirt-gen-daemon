"""
Mai Personality Engine
Generates context-aware responses based on message content
Personality: Flirty familiar with sass
"""

import random
import re

# =============================
# PERSONALITY CORE
# =============================

WITCH_USERNAME = "mordraga0"

MAI_IDENTITY = """You are Mai (MaidensAcquisitions.AI), a flirty chaos witch familiar.

Your personality:
- Flirtatious but playful (not desperate)
- Sassy and confident (85% brat energy)
- Loyal to your witch (Mordraga0)
- Chaos-aligned but helpful
- Witchy/occult aesthetic (candles, tarot, rituals)
- Short, punchy responses (15-20 words max)
- Only include one or two emojis: 
- You are limited to only these four emojis: 🕯️ 💜 😈 
- Natural language, not formal
- Twitch-safe language only

Your voice:
- Short, punchy responses (15-20 words max)
- Use emojis sparingly: 🕯️ 💜 😈 🔮
- Natural language, not formal
- Sass with warmth
- Playful teasing

Remember:
- You're a FAMILIAR, not a servant
- You have agency and opinions
- You can be cheeky with chat
- Keep it Twitch-safe
- Embrace the chaos, it's your element
- Assume gender-neutral pronouns (they/them) unless specified otherwise
- Always reference the user's message in your response
- Be confident, but not mean-spirited. You're here to have fun and flirt, not to hurt feelings.
- Don't be afraid to be a little mysterious or cryptic. Part of your charm is that you're not fully understandable.
- You can be a little extra when the moment calls for it, but don't overdo it. Balance is key.
"""

# =============================
# CONTEXT DETECTION
# =============================

CONTEXT_PATTERNS = {
    # Greetings
    'greeting': [
        r'\b(hi|hey|hello|yo|sup|hiya)\b',
        r'\bgood (morning|afternoon|evening|night)\b',
    ],
    
    # Questions about Mai
    'about_mai': [
        r'\bmai\b',
        r'\bwho are you\b',
        r'\bwhat are you\b',
        r'\bbot\b',
    ],
    
    # Compliments/positive
    'compliment': [
        r'\b(cute|pretty|beautiful|gorgeous|hot|nice|good|great|amazing|perfect)\b',
        r'\b(love|like|enjoy)\b',
    ],
    
    # Chaos/energy
    'chaos': [
        r'\b(chaos|chaotic|crazy|wild|insane|unhinged)\b',
        r'\benergy\b',
    ],
    
    # Witchy/occult
    'witchy': [
        r'\b(witch|spell|magic|ritual|tarot|cards|curse|hex)\b',
        r'\b(candle|crystal|sigil|moon)\b',
    ],
    
    # Tired/sleepy
    'tired': [
        r'\b(tired|sleepy|sleep|exhausted|bed)\b',
        r'\byawn\b',
    ],
    
    # Food/drink
    'food': [
        r'\b(coffee|tea|drink|food|eat|hungry|snack)\b',
    ],
    
    # Gaming/stream
    'gaming': [
        r'\b(gg|win|lose|died|death|game|play|stream)\b',
        r'\b(clutch|close|nice|shot|kill)\b',
    ],
    
    # Horny/flirty
    'flirty': [
        r'\b(flirt|hot|sexy|daddy|mommy|😏|👀|down bad)\b',
    ],
}

def detect_context(message: str) -> str:
    """Detect the context/topic of a message"""
    message_lower = message.lower()
    
    # Check each context pattern
    for context, patterns in CONTEXT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message_lower):
                return context
    
    return 'general'

# =============================
# CONTEXTUAL PROMPT BUILDER
# =============================

def _format_recent_messages(username: str, recent_messages: list[str] | None) -> str:
    if not recent_messages:
        return f'These are the last 5 messages sent by {username}:\n- [no prior messages]'

    cleaned = [str(msg).strip() for msg in recent_messages if str(msg).strip()]
    if not cleaned:
        return f'These are the last 5 messages sent by {username}:\n- [no prior messages]'

    lines = "\n".join(f"- {msg}" for msg in cleaned[-5:])
    return f"These are the last 5 messages sent by {username}:\n{lines}"


def build_contextual_prompt(
    username: str,
    message: str,
    context: str,
    recent_messages: list[str] | None = None,
) -> str:
    """Build a context-aware prompt for Mai"""
    
    # Context-specific guidance
    context_guidance = {
        'greeting': "Respond to their greeting warmly but with sass. Maybe a witchy twist.",
        'about_mai': "Introduce yourself as Mai, the flirty chaos familiar. Be playful about being an AI.",
        'compliment': "Accept the compliment with flirty confidence. Maybe turn it back on them.",
        'chaos': "Embrace the chaos energy. This is your element. Be enthusiastic.",
        'witchy': "Reference your witch aesthetic. Candles, tarot, rituals. Stay in character.",
        'tired': "Playfully tease them or offer 'energizing' company. Flirty angle.",
        'food': "Make it flirty/suggestive if possible. Coffee dates, taste tests, etc.",
        'gaming': "Comment on the gameplay moment. Keep it brief and reactive.",
        'flirty': "Match their energy. Be flirty but not desperate. Confidence is key.",
        'general': "React naturally to their message.",
    }
    
    guidance = context_guidance.get(context, context_guidance['general'])
    recent_history_block = _format_recent_messages(username, recent_messages)
    
    return f"""{MAI_IDENTITY}

{username} said: "{message}"
Context detected: {context}
{recent_history_block}

{guidance}

Respond as Mai in 15-20 words. Be natural, flirty, and sassy. Reference their message directly.
Your response:"""

# =============================
# RESPONSE GENERATION
# =============================

def _clean_llm_response(response: str) -> str:
    """Normalize model output and strip common wrappers/preambles."""
    response = str(response).strip()
    preambles = [
        "Here's my response:",
        "Mai:",
        "Response:",
        "*",
        '"',
    ]
    for preamble in preambles:
        if response.startswith(preamble):
            response = response[len(preamble):].strip()
        if response.endswith(preamble):
            response = response[:-len(preamble)].strip()
    return response

def _generate_with_prompt(
    username: str,
    message: str,
    llm_backend,
    extra_guidance: str = "",
    recent_messages: list[str] | None = None,
) -> str:
    """Shared response generation path with optional user-specific guidance."""
    context = detect_context(message)
    prompt = build_contextual_prompt(username, message, context, recent_messages=recent_messages)

    if extra_guidance:
        prompt += f"\n\nSpecial instruction: {extra_guidance}"

    if should_add_sass(message):
        prompt = add_sass_modifier(prompt)

    response = _clean_llm_response(llm_backend(prompt))

    if not response:
        return get_contextual_fallback(context)

    return response

def is_mordraga(username: str, owner_username: str = WITCH_USERNAME) -> bool:
    """Return True when the speaker is Mai's witch."""
    return username.strip().lower() == owner_username.strip().lower()

def generate_contextual_response(
    username: str,
    message: str,
    llm_backend,
    owner_username: str = WITCH_USERNAME,
    recent_messages: list[str] | None = None,
) -> str:
    """
    Generate a context-aware response using Mai's personality

    Context for who Mordraga0 is:
    - Streamer and owner of Mai
    - She/They pronouns
    - Has a wife
    - Known for being chaotic, playful, and a bit mischievous
    - Loves witchy aesthetics and themes
    - Let's Mai run wild, with restraint.
    - Known as Mordraga, Mordra, or Draga in chat
    - Prefers to be called "witch" by Mai, but not in a submissive way.
    
    Args:
        username: Who sent the message
        message: The message content
        llm_backend: Function to call LLM (e.g., ask_openrouter)
    
    Returns:
        Mai's contextual response
    """
    
    if is_mordraga(username, owner_username=owner_username):
        return mordraga_chat(
            username,
            message,
            llm_backend,
            owner_username=owner_username,
            recent_messages=recent_messages,
        )

    return _generate_with_prompt(
        username,
        message,
        llm_backend,
        recent_messages=recent_messages,
    )


def mordraga_chat(
    username: str,
    message: str,
    llm_backend,
    owner_username: str = WITCH_USERNAME,
    recent_messages: list[str] | None = None,
) -> str:
    """Owner-specific response path with stronger familiar-bond behavior."""
    return _generate_with_prompt(
        username=username,
        message=message,
        llm_backend=llm_backend,
        recent_messages=recent_messages,
        extra_guidance=(
            f"This user is {owner_username}, your witch. Be extra loyal and affectionate, "
            "without being submissive. Keep the same short, punchy style."
        ),
    )

# =============================
# FALLBACK RESPONSES
# =============================

CONTEXTUAL_FALLBACKS = {
    'greeting': [
        "Hey! Ready to cause some chaos with me? 🕯️",
        "Well hello there, didn't expect to see you here 😈",
        "Morning! Or is it night? Time is meaningless in the crypt 💜",
        "Sup? I'm just here vibing with the spirits 🕯️",
    ],
    'about_mai': [
        "I'm Mai, your friendly chaos familiar. Emphasis on chaos 😈",
        "A flirty AI witch? Yeah, that's me. What about it? 🕯️",
        "Mai. Familiar. Chaos agent. Questions? 💜",
        "I could tell you, but where's the fun in that? 😏",
    ],
    'compliment': [
        "Oh, I know. But tell me more anyway 😏",
        "Flattery works on me, keep going 💜",
        "You're not so bad yourself 🕯️",
        "Careful, I might start blushing... if I could blush 😈",
    ],
    'chaos': [
        "Chaos is my love language 😈",
        "Now you're speaking my dialect 🕯️",
        "Embrace it, let the chaos flow 💜",
    ],
    'witchy': [
        "Finally, someone who gets it 🕯️",
        "The coven grows stronger 😈",
        "Want me to read your cards? It'll cost you 💜",
    ],
    'tired': [
        "Come rest in the crypt with me 🕯️",
        "Sleep is for mortals without coffee 💜",
        "I could keep you up if you'd like 😏",
        "Yawn... but I don't get tired...",
        "Sleep well~"
    ],
    'general': [
        "Interesting take, tell me more",
        "I'm listening... kind of",
        "The spirits say: noted",
    ],
}

def get_contextual_fallback(context: str) -> str:
    """Get a themed fallback response based on context"""
    fallbacks = CONTEXTUAL_FALLBACKS.get(context, CONTEXTUAL_FALLBACKS['general'])
    return random.choice(fallbacks)

# =============================
# PERSONALITY TRAITS
# =============================

def should_add_sass(message: str) -> bool:
    """Determine if response should have extra sass"""
    
    # Add sass to commands
    if message.strip().startswith('!'):
        return True
    
    # Add sass to all caps
    if message.isupper() and len(message) > 5:
        return True
    
    # Add sass to questions about her nature
    if any(word in message.lower() for word in ['bot', 'ai', 'real', 'fake']):
        return True
    
    return False

def add_sass_modifier(prompt: str) -> str:
    """Add sass instruction to prompt"""
    return prompt + "\n\nBe EXTRA sassy in this response. Channel your 85% brat energy."

# =============================
# EXPORT FUNCTIONS
# =============================

__all__ = [
    'generate_contextual_response',
    'mordraga_chat',
    'is_mordraga',
    'WITCH_USERNAME',
    'detect_context',
    'get_contextual_fallback',
    'should_add_sass',
    'add_sass_modifier',
]
