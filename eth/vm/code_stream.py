import contextlib
import io
import logging
from typing import (  # noqa: F401
    Iterator,
    Set
)

from eth.validation import (
    validate_is_bytes,
)
from eth.vm import opcode_values

PUSH1, PUSH32 = opcode_values.PUSH1, opcode_values.PUSH32


class CodeStream(object):
    stream = None
    _length_cache = None
    _raw_code_bytes = None
    invalid_positions = None  # type: Set[int]
    valid_positions = None  # type: Set[int]

    logger = logging.getLogger('eth.vm.CodeStream')

    def __init__(self, code_bytes: bytes) -> None:
        validate_is_bytes(code_bytes, title="CodeStream bytes")
        self.stream = io.BytesIO(code_bytes)
        self._raw_code_bytes = code_bytes
        self._length_cache = len(code_bytes)
        self.invalid_positions = set()
        self.valid_positions = set()

    def read(self, size: int) -> bytes:
        return self.stream.read(size)

    def __len__(self) -> int:
        return self._length_cache

    def __iter__(self) -> 'CodeStream':
        return self

    def __next__(self) -> int:
        return self._next()

    def __getitem__(self, i: int) -> int:
        return self._raw_code_bytes[i]

    def _next(self) -> int:
        next_opcode_as_byte = self.read(1)

        if next_opcode_as_byte:
            return ord(next_opcode_as_byte)
        else:
            return opcode_values.STOP

    def peek(self) -> int:
        current_pc = self.pc
        next_opcode = next(self)
        self.pc = current_pc
        return next_opcode

    @property
    def pc(self) -> int:
        return self.stream.tell()

    @pc.setter
    def pc(self, value: int) -> None:
        self.stream.seek(min(value, len(self)))

    @contextlib.contextmanager
    def seek(self, pc: int) -> Iterator['CodeStream']:
        anchor_pc = self.pc
        self.pc = pc
        try:
            yield self
        finally:
            self.pc = anchor_pc

    def _potentially_disqualifying_opcode_positions(self, position: int) -> Iterator[int]:
        # Look at the last 32 positions (from 1 byte back to 32 bytes back).
        # Don't attempt to look at negative positions.
        deepest_lookback = min(32, position)
        # iterate in reverse, because PUSH32 is more common than others
        for bytes_back in range(deepest_lookback, 0, -1):
            earlier_position = position - bytes_back
            opcode = self._raw_code_bytes[earlier_position]
            if PUSH1 + (bytes_back - 1) <= opcode <= PUSH32:
                # that PUSH1, if two bytes back, isn't disqualifying
                # PUSH32 in any of the bytes back is disqualifying
                yield earlier_position

    def is_valid_opcode(self, position: int) -> bool:
        if position >= self._length_cache:
            return False
        elif position in self.invalid_positions:
            return False
        elif position in self.valid_positions:
            return True
        else:
            # An opcode is not valid, iff it is the "data" following a PUSH_
            # So we look at the previous 32 bytes (PUSH32 being the largest) to see if there
            # is a PUSH_ before the opcode in this position.
            for disqualifier in self._potentially_disqualifying_opcode_positions(position):
                # Now that we found a PUSH_ before this position, we check if *that* PUSH is valid
                if self.is_valid_opcode(disqualifier):
                    # If the PUSH_ valid, then the current position is invalid
                    self.invalid_positions.add(position)
                    return False
                # Otherwise, keep looking for other potentially disqualifying PUSH_ codes

            # We didn't find any valid PUSH_ opcodes in the 32 bytes before position; it's valid
            self.valid_positions.add(position)
            return True
