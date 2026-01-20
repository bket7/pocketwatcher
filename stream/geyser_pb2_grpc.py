"""
Yellowstone gRPC Service Stubs (Placeholder)

To generate real stubs, see geyser_pb2.py for instructions.
"""

from typing import AsyncIterator, Any
from .geyser_pb2 import SubscribeRequest, SubscribeUpdate


class GeyserStub:
    """
    gRPC stub for Yellowstone Geyser service.

    This is a placeholder that will be replaced by generated code.
    For real usage, generate from the Yellowstone proto files.
    """

    def __init__(self, channel):
        self.channel = channel

    async def Subscribe(
        self,
        request: SubscribeRequest,
        **kwargs
    ) -> AsyncIterator[SubscribeUpdate]:
        """
        Subscribe to transaction updates.

        This is a placeholder - real implementation is generated from proto.
        """
        raise NotImplementedError(
            "This is a placeholder stub. "
            "Generate real stubs from Yellowstone proto files. "
            "See geyser_pb2.py for instructions."
        )
