"""评估用例 b12 — 逻辑：空值解引用（.get 可能返回 None 后直接取字段）"""
def get_age(user):
    profile = user.get("profile")
    return profile["age"]
