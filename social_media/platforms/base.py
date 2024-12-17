from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
from ..utils import PostContent

logger = logging.getLogger('CityBot2.platforms')

class SocialPlatform(ABC):
    """Base class for all social media platforms."""
    
    def __init__(self, config: Dict[str, Any], city_config: Optional[Dict[str, Any]] = None):
        """
        Initialize platform with configuration and city details.
        
        :param config: Dictionary of platform configuration including credentials
        :param city_config: Optional configuration for the city
        """
        self.config = config
        self.credentials = config.get('credentials', {})
        self.city_config = city_config or {}
        self._client = None

        # Validate credentials
        if not self.credentials:
            logger.warning(f"{self.__class__.__name__}: No credentials provided")

    @abstractmethod
    async def initialize_client(self) -> None:
        """Initialize the platform-specific client."""
        pass

    @abstractmethod
    async def post_update(self, content: PostContent) -> bool:
        """Post content to the platform."""
        pass

    @abstractmethod
    def format_post(self, content: PostContent) -> PostContent:
        """Format content for the platform."""
        pass

    async def close(self) -> None:
        """Clean up resources."""
        try:
            if hasattr(self, '_client') and self._client is not None:
                if hasattr(self._client, 'close'):
                    await self._client.close()
                elif hasattr(self._client, 'logout'):
                    await self._client.logout()
                
                logger.info(f"{self.__class__.__name__}: Client closed successfully")
        except Exception as e:
            logger.error(f"{self.__class__.__name__}: Error closing client - {str(e)}")
        finally:
            self._client = None