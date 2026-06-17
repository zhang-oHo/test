"""Output channels — graph 與輸出通道（LINE / HTTP / Slack...）的解耦層。

對應 spec-23 / task-23。
"""

from app.channels.base import ChannelInput, OutputChannel
from app.channels.http import HttpChannel
from app.channels.line import LineChannel
from app.channels.stub import StubChannel

__all__ = [
    "ChannelInput",
    "OutputChannel",
    "LineChannel",
    "HttpChannel",
    "StubChannel",
]
