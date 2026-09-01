"""
LLM memory adapter - one consumer of ACI (not the definition of ACI).

Gives ANY language model persistent, cross-session, contradiction-checked
memory. Flow:
    1. recall relevant monads for the user's message
    2. inject them as grounding context
    3. (validate the message against memory; surface contradictions)
    4. call the LLM (or a stub) to produce the reply
    5. monadise the exchange back into memory

Pass any callable as `llm` (e.g. an OpenAI/Anthropic wrapper:  llm(prompt)->str).
With no llm, a StubLLM composes a reply from recalled memory so the demo runs
fully offline.
"""

from __future__ import annotations
from typing import Callable, List, Optional

from aci import ACI


class StubLLM:
    """Offline stand-in: answers using only what ACI recalled, to make the
    value of the memory layer visible without any API."""

    def __call__(self, prompt: str) -> str:
        user = prompt
        if "USER:" in prompt:
            user = prompt.split("USER:", 1)[1].split("ASSISTANT:", 1)[0].strip()
        if "MEMORY:" in prompt and "(none)" not in prompt.split("MEMORY:", 1)[1][:20]:
            mem = prompt.split("MEMORY:", 1)[1].split("USER:", 1)[0].strip()
            first = mem.splitlines()[0].lstrip("- ").strip() if mem.strip() else ""
            return f"Based on what I remember ({first}), here is my answer to: {user}"
        return f"I don't have anything in memory about that yet. You said: {user}"


class LLMMemory:
    def __init__(self, aci: ACI, llm: Optional[Callable[[str], str]] = None):
        self.aci = aci
        self.llm = llm or StubLLM()

    def chat(self, user_message: str, k: int = 4, check_contradictions: bool = True) -> dict:
        hits = self.aci.recall(user_message, k=k)
        memory_block = "\n".join(f"- {h.monad.summary}" for h in hits) or "(none)"

        contradiction = None
        if check_contradictions:
            v = self.aci.validate(user_message)
            if not v.is_consistent:
                contradiction = v

        prompt = (f"You are an assistant with persistent memory.\n"
                  f"MEMORY:\n{memory_block}\n"
                  f"USER: {user_message}\n"
                  f"ASSISTANT:")
        reply = self.llm(prompt)

        # Learn from the exchange.
        self.aci.monadise(f"User said: {user_message}", source_type="CHAT")
        return {
            "reply": reply,
            "recalled": [h.monad.summary for h in hits],
            "contradiction": contradiction,
        }

    def remember(self, fact: str, **metadata) -> None:
        """Explicitly store a fact (e.g., 'My accountant is Sarah')."""
        self.aci.monadise(fact, source_type="USER_INPUT", metadata=metadata, truth_value=2.0)
