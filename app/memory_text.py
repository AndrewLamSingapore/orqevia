"""Bounded pure text parsing retained from the retired server; no DB or model side effects."""

import re


ALIASES = {
    "favorite city": ["favourite city", "preferred city", "fav city"],
    "favorite food": ["favourite food", "preferred food"],
    "favorite color": ["favourite color", "favourite colour", "favorite colour"],
    "goal": ["main goal", "primary goal"],
    "project": ["current project"],
    "name": ["my name"],
}


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(s).lower().replace("favourite", "favorite"))).strip()


def canon(s):
    n = norm(s)
    for k, vs in ALIASES.items():
        if n in {norm(k), *(norm(x) for x in vs)}:
            return k
    return re.sub(r"^(my|the|your)\s+", "", n)


def extract_fact(text):
    t = text.strip().rstrip(".!?")[:4096]
    lower = t.lower()
    prefixes = ("please remember that my ", "please remember my ", "remember that my ", "remember my ", "my ")
    prefix = next((value for value in prefixes if lower.startswith(value)), None)
    if prefix is None:
        return None
    body = t[len(prefix) :]
    for suffix in (", remember this", " remember this"):
        if body.lower().endswith(suffix):
            body = body[: -len(suffix)].rstrip()
    if " is " not in body:
        return None
    k, v = body.split(" is ", 1)
    k, v = canon(k), v.strip().rstrip(".!?")
    return (k, v, "preference" if "favorite" in k else "fact") if k and v else None
    return None


def recall_key(text):
    t = norm(text[:4096])
    for pre in [
        "do you know ",
        "do you remember ",
        "can you remember ",
        "remind me of ",
        "tell me ",
        "please tell me ",
    ]:
        if t.startswith(pre):
            t = t[len(pre) :]
    for pre in ("what is my ", "whats my "):
        if t.startswith(pre):
            return canon(t[len(pre) :]) or None
    for k, vs in ALIASES.items():
        if any(x in t for x in {norm(k), *(norm(v) for v in vs)}):
            return k
    return None
