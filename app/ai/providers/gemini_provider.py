from __future__ import annotations

import os


class GeminiLLM:
    """Google Gemini — uses the google-genai SDK."""

    def __init__(self, api_key: str, model: str, temperature: float | None = None) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature

    async def complete(self, prompt: str) -> str:
        kwargs: dict = {"model": self._model, "contents": prompt}
        temperature = getattr(self, "_temperature", None)
        if temperature is not None:
            from google.genai import types
            kwargs["config"] = types.GenerateContentConfig(temperature=temperature)

        try:
            # 1. 嘗試呼叫 API
            response = await self._client.aio.models.generate_content(**kwargs)
            if response.text:
                return response.text
            else:
                raise RuntimeError("Empty response from API")

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                print("!!! API 額度耗盡，啟動離線關鍵字檢索 !!!")

                root_dir = "data/knight"
                found_content = None

                if os.path.exists(root_dir):
                    for dirpath, dirnames, filenames in os.walk(root_dir):
                        for filename in filenames:
                            if not filename.endswith(".md"):
                                continue
                            file_path = os.path.join(dirpath, filename)
                            with open(file_path, "r", encoding="utf-8") as f:
                                content = f.read()

                            first_line = content.split('\n')[0].replace('#', '').strip()
                            title_parts = [p.strip() for p in first_line.replace('(', '：').replace(')', '').split('：') if p.strip()]
                            specific_parts = [p for p in title_parts if len(p) > 2]  # ← 這行要在迴圈內
                            matched = any(part in prompt for part in specific_parts)

                            if matched:
                                found_content = content
                                print(f"DEBUG: 命中！{file_path}")
                                break
                        if found_content:
                            break

                if found_content:
                    return f"【系統離線模式】\n已為您檢索到相關知識：\n\n{found_content}"
                else:
                    return "【系統離線模式】\n抱歉，離線資料庫中找不到與您問題相關的資訊。"

            raise e


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def embed_query(self, text: str) -> list[float]:
        try:
            response = await self._client.aio.models.embed_content(
                model=self._model,
                contents=text.strip(),
            )
            if not response.embeddings:
                raise RuntimeError("Gemini embed_content returned an empty embeddings list")
            return list(response.embeddings[0].values)

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                print("Embedder 偵測到額度限制，無法產生向量。")
                return []   # ← 只有 429 才 return []
            raise   # ← 其他錯誤正常拋出
