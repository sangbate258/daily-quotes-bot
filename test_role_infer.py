from quote_ai_processor import normalize_output
from media_selector import normalize_scene_request, infer_scene_role_intent

quote = {
    "text": "Just when you think it cannot get any worse, it can. And just when you think it cannot get any better, it can.",
    "author": "Nicholas Sparks",
    "source_name": "test",
    "source_url": ""
}

result = normalize_output({}, original_quote=quote)

for i, scene in enumerate(result["scene_plan"], start=1):
    req = normalize_scene_request(scene, i)
    print()
    print("SCENE", i)
    print("scene_role:", req.get("scene_role"))
    print("semantic_goal:", req.get("semantic_goal"))
    print("visual_intent:", req.get("visual_intent"))
    print("inferred:", infer_scene_role_intent(req))