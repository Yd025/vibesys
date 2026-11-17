"""FPGA high-level synthesis domain definition."""

from __future__ import annotations

from vibesys.constants import DomainName
from vibesys.domains.base import DomainDefinition, prompt_dir_beside

DEFINITION = DomainDefinition(
    name=DomainName.FPGA_HLS,
    prompt_dir=prompt_dir_beside(__file__),
)
