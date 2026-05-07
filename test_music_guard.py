from quote_ai_processor import normalize_output

quote = {
    "text": "Piglet sidled up to Pooh from behind. 'Pooh?' he whispered. 'Yes, Piglet?' 'Nothing,' said Piglet, taking Pooh's paw. 'I just wanted to be sure of you.'",
    "author": "A.A. Milne",
    "source_name": "test",
    "source_url": "",
}

result = normalize_output(
    {
        "classification": {
            "lane": "relationships",
            "mood": "sad",
            "music_mood_tag": "sad",
            "literal_possible": True,
        },
        "visual_plan": {
            "motif_main": "Two cute friends connecting",
            "visual_world": "pastel meme quote style",
        },
        "scene_plan": [
            {
                "scene_id": 1,
                "scene_role": "setup",
                "meaning": "Piglet shyly approaches Pooh from behind.",
                "visual_goal": "A small cute character cautiously approaching a friend.",
                "queries_giphy": ["cute animal walking slowly"],
            },
            {
                "scene_id": 2,
                "scene_role": "payoff",
                "meaning": "Piglet takes Pooh's paw to feel reassured.",
                "visual_goal": "Two cute friends holding hands or hugging for reassurance.",
                "queries_giphy": ["cute animal friends hug"],
            },
        ],
    },
    original_quote=quote,
)

print("mood:", result["mood"])
print("music_mood_tag:", result["music_mood_tag"])