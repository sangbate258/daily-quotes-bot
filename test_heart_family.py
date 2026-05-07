from media_selector import infer_retry_family

scene = {
    "scene_id": 2,
    "scene_role": "payoff",
    "meaning": "The feeling is shown through a warm heart.",
    "visual_goal": "A warm heart or soft feeling, not romantic love.",
    "semantic_goal": "Show emotion and feeling rather than love attachment.",
    "visual_intent": "thought bubble vs heart/feeling",
    "must_have_elements": ["heart", "feeling", "emotion"],
    "queries_giphy": ["cute cat heart", "happy animal daydream", "sparkle heart sticker"],
}

print(infer_retry_family(scene))