def normalize_hindi_numbers(text: str) -> str:
    text = text.lower()

    numbers = {
        "ek": 1,
        "do": 2,
        "teen": 3,
        "char": 4,
        "chaar": 4,
        "paanch": 5,
        "panch": 5,
        "chhe": 6,
        "saat": 7,
        "aath": 8,
        "nau": 9,
        "das": 10,
        "gyarah": 11,
        "barah": 12,
    }

    multipliers = {
        "sau": 100,
        "hazaar": 1000,
    }

    words = text.split()
    result = []
    i = 0

    while i < len(words):
        w = words[i]

        # barah sau → 1200
        if w in numbers and i + 1 < len(words) and words[i + 1] in multipliers:
            result.append(str(numbers[w] * multipliers[words[i + 1]]))
            i += 2
            continue

        # do → 2
        if w in numbers:
            result.append(str(numbers[w]))
            i += 1
            continue

        # remove filler words
        if w in ["rupaye", "rupees", "rs", "rate", "ka", "ke", "mein"]:
            i += 1
            continue

        result.append(w)
        i += 1

    return " ".join(result)