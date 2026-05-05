def deduplicate_questions(questions):
    seen = set()
    unique = []

    for q in questions:
        text = q.get("question", "").strip()
        if text and text not in seen:
            seen.add(text)
            unique.append(q)

    return unique