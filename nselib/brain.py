"""
Brain — Claude-powered intelligence layer.

Wraps the Anthropic Messages API with an agentic tool loop so that
natural language queries automatically call the right NSE data methods.
"""

import json
from typing import Any, Callable

import anthropic

_SYSTEM = """You are an expert Indian equity market analyst with deep knowledge of \
NSE-listed stocks, indices, F&O markets, and corporate events. You have access to \
live NSE data through tools. Be concise, accurate, and data-driven. When asked about \
a stock, always fetch the actual data rather than relying on memory — prices change. \
Format numbers clearly: use ₹ for prices, % for changes, and commas for large numbers."""


class Brain:
    """
    Claude-powered intelligence layer for the NSE library.

    Registers NSE data methods as tools, then runs an agentic loop
    so Claude can fetch and reason about live market data to answer
    natural language questions.
    """

    def __init__(self, api_key: str, model: str = "claude-haiku-5-5"):
        self._client  = anthropic.Anthropic(api_key=api_key)
        self._model   = model
        self._tools: list[dict]          = []
        self._fns:   dict[str, Callable] = {}

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

    def ask(self, query: str) -> str:
        """
        Run an agentic loop: Claude calls registered tools until it
        has enough data to answer, then returns a text response.
        """
        messages: list[dict] = [{"role": "user", "content": query}]

        while True:
            resp = self._client.messages.create(
                model      = self._model,
                max_tokens = 1024,
                system     = _SYSTEM,
                tools      = self._tools,
                messages   = messages,
            )

            if resp.stop_reason == "end_turn":
                return next(
                    (b.text for b in resp.content if hasattr(b, "text")), ""
                )

            if resp.stop_reason != "tool_use":
                break

            # Execute tool calls, feed results back
            messages.append({"role": "assistant", "content": resp.content})
            results = []

            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    data = self._fns[block.name](**block.input)
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
