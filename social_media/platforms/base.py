from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class MediaContent:
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    link_url: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None

@dataclass
class PostContent:
    text: str
    media: Optional[MediaContent] = None
    platform_specific: Dict[str, Any] = None

class SocialPlatform(ABC):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.initialize()

    @abstractmethod
    def initialize(self):
        """Initialize platform-specific client."""
        pass

    @abstractmethod
    async def post_update(self, content: PostContent) -> bool:
        """Post update to platform."""
        pass

    @abstractmethod
    def format_post(self, content: PostContent) -> PostContent:
        """Format post for platform-specific requirements."""
        pass