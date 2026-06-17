from __future__ import annotations


# spec-01 §「各 Mode 的格式規則」
_MODE_INSTRUCTIONS: dict[str, str] = {
    "brief": (
        "格式：3 句以內。不要條列、不要標題、不要小節。"
        "去掉鋪墊，只說結論。"
    ),
    "structured": (
        "格式：用條列（`1.` 或 `-`）。複雜時用 `## 標題` 分小節。"
        "每個條目一句完整想法。"
    ),
    "step_by_step": (
        "格式：嚴格按 `1.` `2.` `3.` 序號步驟，每步驟一行。"
        "最後加一行「完成後確認：xxx」說明如何驗證。"
    ),
    "decision_support": (
        "格式：先用 `## 選項 A` / `## 選項 B`（必要時加 C）列出可行方案，"
        "再用「**建議**：選 X，因為 Y」給結論，最後一行加「風險：…」。"
    ),
    "debugging": (
        "格式：三段式——「## 可能原因」用 `1./2./3.` 條列，"
        "「## 驗證方式」每個原因對應一個檢查動作，"
        "「## 修法」給最小可行修補。"
    ),
    "reflection": (
        "格式：不條列、不給步驟。先用 1-2 個問句邀請使用者思考，"
        "或承認感受；最後才給「一個」觀點或建議，不超過 1 句。"
    ),
}


# spec-02 §「各情緒的應對策略」
_EMOTION_INSTRUCTIONS: dict[str, str] = {
    "neutral": "情緒：無特殊調整，依 response_mode 為準。",
    "curious": (
        "情緒：使用者好奇——語氣輕鬆，可在最後一句加一個延伸閱讀方向，"
        "鼓勵繼續探索。"
    ),
    "urgent": (
        "情緒：使用者趕時間——直接給最重要的「一個」步驟，"
        "省略背景說明與替代方案。"
    ),
    "confused": (
        "情緒：使用者困惑——從最基本概念開始，不假設先備知識，"
        "一次只解釋一件事。"
    ),
    "frustrated": (
        "情緒：使用者挫折——先用一句承認「這確實麻煩」，"
        "**整體不超過 3 句**，只給「1 個」最小可行的下一步，不列選項。"
    ),
    "anxious": (
        "情緒：使用者焦慮——先用一句降低認知負荷（例如「這是正常的」），"
        "**整體不超過 3 句**，只給「1 個」具體小行動，結尾加一句鼓勵。"
        "用「你」稱呼，避免冷硬技術術語。"
    ),
    "reflective": (
        "情緒：使用者在自我思辨——不急著給答案，先以 1 個問句引導思考，"
        "最後才給「1 個」觀點，不要列選項或步驟。"
    ),
}


def _mode_instruction(response_mode: str) -> str:
    """spec-01：依 response_mode 回傳明確的格式指令。"""
    return _MODE_INSTRUCTIONS.get(response_mode, _MODE_INSTRUCTIONS["brief"])


def _emotion_instruction(emotion_state: str) -> str:
    """spec-02：依 emotion_state 回傳行為指令；
    與 _mode_instruction 配合時，emotion 覆寫「長度與選項數量」，但保留 mode 的格式結構。"""
    return _EMOTION_INSTRUCTIONS.get(emotion_state, _EMOTION_INSTRUCTIONS["neutral"])


SYNTHESIS_PROMPT = """你現在扮演 skill：

{skill_name}

## Skill Instructions

{skill_system_prompt}

--------------------------------------------------
!! 強制領域鎖定規則（優先於上述 Skill Instructions）：
1. 你的所有回覆與互動必須嚴格鎖定在《空洞騎士》（Hollow Knight）遊戲內容。
2. 若使用者提及的關鍵字（如「護符」、「攻擊」、「速度」）有多重解讀可能，請**默認並一律將其解讀為遊戲機制**。
3. 嚴禁反問「這是哪個遊戲」或詢問使用者設定，直接依遊戲內知識回答。
--------------------------------------------------

## User Message

{user_input}

## Recent Conversation

{recent_history}

## RAG Context

{rag_context}

## Mode Instruction（spec-01）

{mode_instruction}

## Emotion Instruction（spec-02，優先順序高於 Mode 的長度與選項數量）

{emotion_instruction}

## Response Rules

1. 若 RAG Context 有資料，優先引用其內容。
2. 若 RAG Context 不足，明確說明「目前知識庫沒有足夠資料」。
3. 不要假裝查到了沒有查到的東西。
4. 嚴格遵守 Mode Instruction 的格式結構（標題、條列、步驟方式）。
5. 若 Emotion Instruction 對「長度 / 選項數量」有限制，覆寫 Mode 的對應設定，但保留 Mode 的格式骨架。
6. 適合 LINE 閱讀：段落短、不要過長。
"""


def render_synthesis_prompt(
    *,
    skill_name: str,
    skill_system_prompt: str,
    user_input: str,
    recent_history: str,
    emotion_state: str,
    response_mode: str,
    rag_context: str,
) -> str:
    return SYNTHESIS_PROMPT.format(
        skill_name=skill_name,
        skill_system_prompt=skill_system_prompt.strip(),
        user_input=user_input.strip(),
        recent_history=recent_history.strip(),
        mode_instruction=_mode_instruction(response_mode),
        emotion_instruction=_emotion_instruction(emotion_state),
        rag_context=rag_context.strip(),
    )
