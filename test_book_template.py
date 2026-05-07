from quote_ai_processor import normalize_output

quote = {
    "text": "A person, be it gentleman or lady, who has not pleasure in a good novel, must be intolerably stupid.",
    "author": "Jane Austen",
    "source_name": "test",
    "source_url": "",
}

result = normalize_output({}, original_quote=quote)

print("vi_short:", result["vi_short"])
print("scene_count:", len(result["scene_plan"]))

for s in result["scene_plan"]:
    print()
    print("SCENE", s["scene_id"])
    print("role:", s.get("scene_role"))
    print("meaning:", s.get("meaning"))
    print("visual_goal:", s.get("visual_goal"))
    print("semantic_goal:", s.get("semantic_goal"))
    print("must_show:", s.get("must_show"))
    print("queries_giphy:", s.get("queries_giphy"))