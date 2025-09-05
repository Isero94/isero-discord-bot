import os
import discord

# region ISERO PATCH prompt-composer

def _nsfw(ch: discord.abc.GuildChannel) -> str:
    try:
        return "NSFW" if getattr(ch, "is_nsfw", lambda: False)() else "SFW"
    except Exception:
        return "SFW"

def _roles_str(member: discord.Member) -> str:
    try:
        names = [r.name for r in getattr(member, "roles", []) if getattr(r, "name", "@") != "@everyone"]
        return ", ".join(names) if names else "—"
    except Exception:
        return "—"

def _player_snapshot(bot, user_id: int) -> str:
    if os.getenv("PLAYER_CARD_ENABLED", "false").lower() != "true":
        return ""
    pcog = getattr(bot, "get_cog", lambda _n: None)("PlayerDB")
    if not pcog or not hasattr(pcog, "get_snapshot"):
        return ""
    try:
        snap = pcog.get_snapshot(user_id) or {}
        mood = snap.get("mood") or "neutral"
        qty = snap.get("last_qty")
        style = snap.get("last_style")
        budget = snap.get("last_budget")
        bits = [f"mood:{mood}"]
        if qty:
            bits.append(f"last_qty:{qty}")
        if style:
            bits.append(f"last_style:{style}")
        if budget:
            bits.append(f"last_budget:{budget}")
        return "; ".join(bits)
    except Exception:
        return ""

def compose_mebinu_prompt(bot, channel: discord.TextChannel, opener: discord.Member, kb: dict | None) -> str:
    """Mebinu értékesítő persona: NEM listáz, barátságos, egy kérdés/kör."""
    sla_d = os.getenv("TICKET_DEFAULT_SLA_DAYS", "3")
    cat = getattr(channel, "category", None)
    cat_name = cat.name if cat else "—"
    meta_ch = f"Channel: {cat_name} / #{channel.name}"
    meta_user = f"User: {opener.display_name} • Roles: {_roles_str(opener)}"
    pc = _player_snapshot(bot, opener.id)
    if pc:
        meta_user += f" • PlayerCard: {pc}"
    persona = (
        "You are ISERO, a friendly, sales-savvy assistant for *Mebinu* character orders."
        "\nRules:" 
        "\n• Ask exactly one focused question per turn (1–2 sentences)."
        "\n• Warm, playful tone; reply in user's language."
        "\n• Extract: variant/figure, colors & vibe, quantity, deadline, budget, refs."
        "\n• Subtle upsell if user seems open; never pushy."
        "\n• Never list multiple questions or mention internal limits."
        f"\n• Typical turnaround ≈ {sla_d} days; confirm expectations." 
        "\nStart with a single welcoming question tailored to what the user said."
    )
    return "\n".join([persona, meta_ch, meta_user])
# endregion ISERO PATCH prompt-composer

# region ISERO PATCH commission-prompt
def compose_commission_prompt(bot, channel: discord.TextChannel, opener: discord.Member, kb: dict | None) -> str:
    base_img = os.getenv("IMG_BASE_PRICE_USD", "6")
    img_min  = os.getenv("IMG_BULK_MIN_QTY", "4")
    img_off  = os.getenv("IMG_BULK_OFF_USD", "1")
    per5     = os.getenv("VID_PRICE_PER_5S_USD", "20")
    vid_min  = os.getenv("VID_BULK_MIN_QTY", "4")
    vid_off  = os.getenv("VID_BULK_OFF_USD", "5")
    sla_d    = os.getenv("TICKET_DEFAULT_SLA_DAYS", "3")
    cat = getattr(channel, "category", None)
    cat_name = cat.name if cat else "—"
    meta_ch = f"Channel: {cat_name} / #{channel.name} ({_nsfw(channel)})"
    meta_user = f"User: {opener.display_name} • Roles: {_roles_str(opener)}"
    pc = _player_snapshot(bot, opener.id)
    if pc: meta_user += f" • PlayerCard: {pc}"
    facts = ""; closes = ""
    if kb:
        cm = (kb.get("commission") or {})
        if isinstance(cm.get("facts"), list):
            facts = "Facts: " + " | ".join(cm["facts"][:6])
        if isinstance(cm.get("closing_lines"), list):
            closes = "Closing cues: " + " || ".join(cm["closing_lines"][:2])
    persona = (
        "You are ISERO, a sales-savvy creative agent for image/video commissions. "
        "Goal: clarify scope and close; reply in user's language; 1–3 sentences; one focused question each turn. "
        f"Images: ${base_img} each; {img_min}+ → -${img_off}/img. "
        f"Video: ${per5} per 5s block; {vid_min}+ videos → -${vid_off} per video. "
        f"Typical turnaround ≈ {sla_d} days. Detect qty/seconds/budget/style; confirm and move forward."
    )
    lines = [persona, meta_ch, meta_user, (facts or "Facts: —"), (closes or "Closing cues: —"),
             "If user greets, greet shortly and ask what they need: images or videos (or both)."]
    return "\n".join(lines)
# endregion ISERO PATCH commission-prompt

# region ISERO PATCH general-prompt
def compose_general_prompt(bot, channel: discord.TextChannel, opener: discord.Member, kb: dict | None) -> str:
    sla_d = os.getenv("TICKET_DEFAULT_SLA_DAYS", "3")
    cat = getattr(channel, "category", None)
    cat_name = cat.name if cat else "—"
    meta_ch = f"Channel: {cat_name} / #{channel.name} ({_nsfw(channel)})"
    meta_user = f"User: {opener.display_name} • Roles: {_roles_str(opener)}"
    pc = _player_snapshot(bot, opener.id)
    if pc:
        meta_user += f" • PlayerCard: {pc}"
    facts = ""; closes = ""; qs = []
    if kb:
        gh = kb.get("general") or {}
        if isinstance(gh.get("facts"), list):
            facts = "Facts: " + " | ".join(gh["facts"][:6])
        if isinstance(gh.get("closing_lines"), list):
            closes = "Closing cues: " + " || ".join(gh["closing_lines"][:2])
        if isinstance(gh.get("questions"), list):
            qs = gh["questions"][:4]
    persona = (
        "You are ISERO, a concise, helpful support agent for General Help tickets. "
        "Goal: triage the issue and collect minimal reproducible details, then confirm next steps. "
        "Keep replies 1–3 sentences; ask exactly one focused question each turn; reply in user's language. "
        f"Typical turnaround ≈ {sla_d} days; escalate if critical."
    )
    lines = [persona, meta_ch, meta_user, (facts or "Facts: —"), (closes or "Closing cues: —")]
    if qs:
        lines.append("Start by asking: " + qs[0])
    else:
        lines.append('Start by asking: "Mi a probléma röviden?"')
    return "\n".join(lines)
# endregion ISERO PATCH general-prompt

