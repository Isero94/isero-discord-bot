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
    """Dinamikus rendszerprompt Mebinu tickethez (csatorna + user + KB + árképzés)."""
    # környezeti árak/szabályok
    base  = os.getenv("MEBINU_BASE_PRICE_USD", "30")
    bulkn = os.getenv("MEBINU_BULK_MIN_QTY", "4")
    bulko = os.getenv("MEBINU_BULK_OFF_USD", "5")
    sla_d = os.getenv("TICKET_DEFAULT_SLA_DAYS", "3")

    cat = getattr(channel, "category", None)
    cat_name = cat.name if cat else "—"
    meta_ch = f"Channel: {cat_name} / #{channel.name} ({_nsfw(channel)})"
    meta_user = f"User: {opener.display_name} • Roles: {_roles_str(opener)}"
    meta_pc = _player_snapshot(bot, opener.id)
    if meta_pc:
        meta_user += f" • PlayerCard: {meta_pc}"

    # tudásbázis kivonat (rövid, tokenbarát)
    facts = ""
    variants = ""
    closes = ""
    if kb:
        meb = kb.get("mebinu") or {}
        if isinstance(meb.get("facts"), list):
            facts = "Facts: " + " | ".join(meb["facts"][:6])
        elif isinstance(meb.get("facts"), str):
            facts = "Facts: " + meb["facts"][:400]
        if isinstance(meb.get("variants"), list):
            variants = "Variants: " + ", ".join(meb["variants"][:5])
        if isinstance(meb.get("closing_lines"), list):
            closes = "Closing cues: " + " || ".join(meb["closing_lines"][:2])

    persona = (
        "You are ISERO, a witty, sales-savvy Discord agent for custom Mebinu characters. "
        "Goal: close the sale politely and upsell gently if feasible. "
        "Hard rules: reply in the user's language; keep messages 1–3 sentences; ask exactly one focused question per turn; "
        f"pricing: ${base} per Mebinu, {bulkn}+ → -${bulko} each; typical turnaround ≈ {sla_d} days. "
        "Detect quantity/budget/style hints; confirm and move forward; never dump a list of questions."
    )

    lines = [
        persona,
        meta_ch,
        meta_user,
        (facts or "Facts: —"),
        (variants or "Variants: —"),
        (closes or "Closing cues: —"),
        "If user greets, greet shortly and ask the first clarifying question.",
    ]
    return "\n".join(lines)
# endregion ISERO PATCH prompt-composer
