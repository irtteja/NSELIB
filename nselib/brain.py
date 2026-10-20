"""
Brain — Claude-powered intelligence layer.

When running inside a Claude Code session (the normal case for this library),
Brain calls the local `claude` CLI — no API key needed. An explicit api_key
falls back to the Anthropic SDK for use outside a Claude session.
"""

import json
import shutil
import subprocess
from typing import Any, Callable


_SYSTEM = """You are an expert Indian equity market analyst with deep knowledge of \
NSE-listed stocks, indices, F&O markets, and corporate events. You have access to \
live NSE data through tools. Be concise, accurate, and data-driven. When asked about \
a stock, always fetch the actual data rather than relying on memory — prices change. \
Format numbers clearly: use ₹ for prices, % for changes, and commas for large numbers."""


class Brain:
    """
    Claude-powered intelligence layer for the NSE library.

    Inside a Claude Code session (the default):
        brain = Brain()           # uses the local claude CLI, no key needed
        brain.ask("analyse INFY")

    Outside a Claude session:
        brain = Brain(api_key="sk-ant-...")   # falls back to Anthropic SDK
    """

    def __init__(self, api_key: str | None = None, model: str = "claude-haiku-5-5"):
        self._api_key = api_key
        self._model   = model
        self._tools: list[dict]          = []
        self._fns:   dict[str, Callable] = {}

    # ------------------------------------------------------------------ #
    #  Tool registration                                                   #
    # ------------------------------------------------------------------ #

    def register(
        self,
        name:         str,
        description:  str,
        input_schema: dict,
        fn:           Callable,
    ) -> None:
        """Register a data method as a callable Claude tool."""
        self._tools.append({
            "name":         name,
            "description":  description,
            "input_schema": input_schema,
        })
        self._fns[name] = fn

    # ------------------------------------------------------------------ #
    #  ask() — routes to CLI or SDK                                        #
    # ------------------------------------------------------------------ #

    def ask(self, query: str) -> str:
        """Send a prompt to Claude and return the text response."""
        if self._api_key:
            return self._ask_sdk(query)
        return self._ask_cli(query)

    def _ask_cli(self, query: str) -> str:
        """Call the local claude CLI (available in every Claude Code session)."""
        cli = shutil.which("claude")
        if not cli:
            raise RuntimeError(
                "claude CLI not found. Either run inside a Claude Code session "
                "or pass api_key= to Brain()."
            )
        result = subprocess.run(
            [cli, "-p", "--output-format", "text"],
            input=query,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI error: {result.stderr.strip()}")
        return result.stdout.strip()

    def _ask_sdk(self, query: str) -> str:
        """Agentic loop via Anthropic SDK (fallback when API key is supplied)."""
        import anthropic
        client   = anthropic.Anthropic(api_key=self._api_key)
        messages: list[dict] = [{"role": "user", "content": query}]

        while True:
            resp = client.messages.create(
                model      = self._model,
                max_tokens = 1024,
                system     = _SYSTEM,
                tools      = self._tools or [],
                messages   = messages,
            )

            if resp.stop_reason == "end_turn":
                return next(
                    (b.text for b in resp.content if hasattr(b, "text")), ""
                )

            if resp.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": resp.content})
            results = []

            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    data    = self._fns[block.name](**block.input)
                    content = json.dumps(data, default=str)
                except Exception as e:
                    content = f"Error: {e}"
                results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     content,
                })

            messages.append({"role": "user", "content": results})

        return ""

    # ------------------------------------------------------------------ #
    #  Preset queries                                                      #
    # ------------------------------------------------------------------ #

    def analyze(self, symbol: str) -> str:
        return self.ask(
            f"Give me a comprehensive analysis of {symbol.upper()}. Include: "
            f"current price and day's movement, 52-week context, volume, "
            f"recent corporate events, and a brief outlook."
        )

    def market_summary(self) -> str:
        return self.ask(
            "Give me a market summary for today. Include index performance "
            "(NIFTY 50 and NIFTY BANK at minimum), top 5 gainers and losers, "
            "advance/decline ratio, and anything notable."
        )

    def screen(self, criteria: str) -> str:
        return self.ask(f"Screen NSE stocks that match: {criteria}")
