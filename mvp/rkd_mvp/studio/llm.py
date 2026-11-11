"""Model access for the studio: one OpenAI-compatible channel, strict accounting.

Keys come from the environment only (RKD_AI_BASE_URL / RKD_AI_MODEL / RKD_AI_API_KEY).
Nothing is written to disk. Every call reports token usage back to the caller so a
run can be stopped at the budget.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class ModelError(RuntimeError):
    """Raised when the channel is missing, unreachable or returns an unusable answer."""


class BudgetExceeded(RuntimeError):
    """Raised when a run would exceed the token ceiling agreed with the boss."""


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0

    def add(self, tin: int, tout: int) -> None:
        self.tokens_in += tin
        self.tokens_out += tout
        self.calls += 1

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out

    def as_dict(self) -> dict:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "tokens_total": self.total, "calls": self.calls}


@dataclass
class Config:
    base_url: str
    model: str
    api_key: str | None
    timeout: int = 120
    run_token_limit: int = 600_000
    project_token_limit: int = 2_000_000

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            base_url=(os.environ.get("RKD_AI_BASE_URL") or "https://api.codelink.chat/v1").rstrip("/"),
            model=(os.environ.get("RKD_AI_MODEL") or "gpt-5.6-sol"),
            api_key=os.environ.get("RKD_AI_API_KEY") or None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


class Client:
    def __init__(self, config: Config | None = None, usage: Usage | None = None,
                 project_tokens: int = 0) -> None:
        self.config = config or Config.from_env()
        self.usage = usage or Usage()
        self.project_tokens = project_tokens
        self.supports_tools: bool | None = None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ------------------------------------------------------------------ budget
    def _guard(self, projected: int = 0) -> None:
        if self.usage.total + projected > self.config.run_token_limit:
            raise BudgetExceeded(
                f"本次回路已用 {self.usage.total:,} tokens，接近上限 "
                f"{self.config.run_token_limit:,}，已停止并等待老板确认。")
        if self.project_tokens + self.usage.total + projected > self.config.project_token_limit:
            raise BudgetExceeded(
                f"本项目累计 {self.project_tokens + self.usage.total:,} tokens，超过 "
                f"{self.config.project_token_limit:,} 上限，已停止并等待老板确认。")

    # ------------------------------------------------------------------- HTTP
    def _post(self, path: str, body: dict) -> dict:
        if not self.config.configured:
            raise ModelError("未配置模型通道：环境变量 RKD_AI_API_KEY 不存在。"
                             "密钥只在会话环境变量里，不写入任何文件。")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.base_url}{path}", data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.config.api_key}"})
        last: Exception | None = None
        for attempt in range(2):
            try:
                with self._opener.open(req, timeout=self.config.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                # a channel that does not implement tools: remember and retry without
                if exc.code == 400 and "tool" in detail.lower():
                    raise ModelError(f"TOOLS_UNSUPPORTED:{detail}") from exc
                last = ModelError(f"模型通道返回 {exc.code}：{detail}")
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(2 + attempt * 3)
                    continue
                raise last
            except Exception as exc:  # timeout / connection reset
                last = ModelError(f"模型通道连接失败：{type(exc).__name__}: {exc}")
                time.sleep(2 + attempt * 3)
        raise last or ModelError("模型通道未知错误")

    # ------------------------------------------------------------------- chat
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.6, max_tokens: int = 3000,
             json_only: bool = False) -> dict:
        body: dict = {"model": self.config.model, "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens}
        if json_only:
            body["response_format"] = {"type": "json_object"}
        use_tools = tools if (tools and self.supports_tools is not False) else None
        if use_tools:
            body["tools"] = use_tools
            body["tool_choice"] = "auto"
        self._guard(projected=max_tokens)
        try:
            raw = self._post("/chat/completions", body)
        except ModelError as exc:
            if str(exc).startswith("TOOLS_UNSUPPORTED"):
                self.supports_tools = False
                body.pop("tools", None)
                body.pop("tool_choice", None)
                raw = self._post("/chat/completions", body)
            elif "response_format" in body:
                body.pop("response_format", None)
                raw = self._post("/chat/completions", body)
            else:
                raise
        else:
            if use_tools and self.supports_tools is None:
                self.supports_tools = True
        try:
            choice = raw["choices"][0]["message"]
        except Exception as exc:
            raise ModelError(f"模型返回结构异常：{str(raw)[:300]}") from exc
        usage = raw.get("usage") or {}
        tin = int(usage.get("prompt_tokens") or 0)
        tout = int(usage.get("completion_tokens") or 0)
        self.usage.add(tin, tout)
        return {"content": (choice.get("content") or "").strip(),
                "tool_calls": choice.get("tool_calls") or [],
                "usage": {"in": tin, "out": tout}, "model": self.config.model}


    # ------------------------------------------------------------------ vision
    def chat_vision(self, messages: list[dict], images: list[tuple[bytes, str]],
                    temperature: float = 0.4, max_tokens: int = 1000,
                    json_only: bool = False) -> dict:
        """One visual turn. `images` are (jpeg_bytes, mime) pairs.

        Used only for the director's impression of our own generated images.
        The answer stays an opinion; it is never a pass/fail verdict.
        """
        body_messages: list[dict] = []
        for idx, m in enumerate(messages):
            if idx == len(messages) - 1 and m["role"] == "user":
                content: list[dict] = [{"type": "text", "text": m["content"]}]
                for data, mime in images:
                    content.append({"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}})
                body_messages.append({"role": "user", "content": content})
            else:
                body_messages.append(m)
        body: dict = {"model": self.config.model, "messages": body_messages,
                      "temperature": temperature, "max_tokens": max_tokens}
        if json_only:
            body["response_format"] = {"type": "json_object"}
        self._guard(projected=max_tokens)
        try:
            raw = self._post("/chat/completions", body)
        except ModelError:
            if "response_format" in body:
                body.pop("response_format", None)
                raw = self._post("/chat/completions", body)
            else:
                raise
        choice = raw["choices"][0]["message"]
        usage = raw.get("usage") or {}
        tin = int(usage.get("prompt_tokens") or 0)
        tout = int(usage.get("completion_tokens") or 0)
        self.usage.add(tin, tout)
        return {"content": (choice.get("content") or "").strip(),
                "usage": {"in": tin, "out": tout}, "model": self.config.model,
                "image_count": len(images)}


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model answer (tolerates ``` fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
    t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start = t.find("{")
        end = t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise
