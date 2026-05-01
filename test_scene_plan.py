from quote_ai_processor import normalize_output

quote = {
    "text": "Just when you think it cannot get any worse, it can. And just when you think it cannot get any better, it can.",
    "author": "Nicholas Sparks",
    "source_name": "test",
    "source_url": ""
}

result = normalize_output({}, original_quote=quote)

for s in result["scene_plan"]:
    print()
    print("SCENE", s["scene_id"])
    print("role:", s.get("scene_role"))
    print("meaning:", s.get("meaning"))
    print("semantic_goal:", s.get("semantic_goal"))
    print("visual_intent:", s.get("visual_intent"))
    print("must_show:", s.get("must_show"))
    print("queries:", s.get("queries_giphy"))