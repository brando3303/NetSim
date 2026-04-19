
from dataclasses import dataclass

from typing import Any


@dataclass
class Packet:
    def __init__(self, data: Any, src: str, dst: str):
        self.src = src
        self.dst = dst
        self.data = data
    
    def __len__(self):
        return len(self.data)
    
