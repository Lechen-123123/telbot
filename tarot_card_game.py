import random

def tarot_game() -> str:
    tarot_cards = [
        {"name": "The Fool", "meaning": "New beginnings and freedom"},
        {"name": "The Magician", "meaning": "Resourcefulness and self-confidence"},
        {"name": "The High Priestess", "meaning": "Intuition and hidden wisdom"},
        {"name": "The Empress", "meaning": "Motherhood and abundance"},
        {"name": "The Emperor", "meaning": "Authority and stability"},
        {"name": "The Hierophant", "meaning": "Tradition and faith"},
        {"name": "The Lovers", "meaning": "Choice and relationships"},
        {"name": "The Chariot", "meaning": "Determination and victory"}
    ]
    card = random.choice(tarot_cards)
    return f"You drew: {card['name']}, Interpretation: {card['meaning']}"