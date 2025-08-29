def normalize_token(s: str) -> str:
    mapping = {
        "ISSZERO": "ISERO",
        "ISERU": "ISERO",
        "Isaru": "ISERO",
        "Comission": "Commission",
        "NSFV": "NSFW 18+",
        "NSFW18+": "NSFW 18+",
    }
    return mapping.get(s, s)
