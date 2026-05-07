from quote_ai_processor import normalize_output

quote = {
    "text": "A mind needs books as a sword needs a whetstone, if it is to keep its edge.",
    "author": "George R.R. Martin",
    "source_name": "test",
    "source_url": "",
}

result = normalize_output(
    {
        "classification": {
            "lane": "wisdom",
            "mood": "reflective",
            "music_mood_tag": "reflective",
            "literal_possible": True,
        },
        "visual_plan": {
            "motif_main": "sharpening/growth",
            "visual_world": "pastel meme quote style",
        },
        "scene_plan": [
            {
                "scene_id": 1,
                "scene_role": "setup",
                "meaning": "A confused mind needs sharpening.",
                "visual_goal": "A confused cute character thinking.",
                "queries_giphy": ["confused cartoon thinking"],
            },
            {
                "scene_id": 2,
                "scene_role": "contrast",
                "meaning": "Reading books sharpens the mind.",
                "visual_goal": "A cute character reading books.",
                "queries_giphy": ["cartoon reading book"],
            },
            {
                "scene_id": 3,
                "scene_role": "payoff",
                "meaning": "The mind becomes sharper and gets a eureka moment.",
                "visual_goal": "A lightbulb moment cartoon.",
                "queries_giphy": ["lightbulb moment cartoon"],
            },
        ],
    },
    original_quote=quote,
)

print("mood:", result["mood"])
print("music_mood_tag:", result["music_mood_tag"])