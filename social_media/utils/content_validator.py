import logging
from typing import Dict, List, Optional
import re
from urllib.parse import urlparse
from PIL import Image
import os

logger = logging.getLogger('CityBot2.validator')

class ContentValidator:
    def __init__(self):
        self.platform_limits = {
            'bluesky': {'text': 300, 'images': 4},
            'twitter': {'text': 280, 'images': 4},
            'facebook': {'text': 63206, 'images': 10},
            'linkedin': {'text': 3000, 'images': 9},
            'reddit': {'text': 40000, 'images': 20},
            'instagram': {'text': 2200, 'images': 10}
        }
        
        self.image_requirements = {
            'max_size': 5 * 1024 * 1024,  # 5MB
            'min_dimensions': (200, 200),
            'max_dimensions': (4096, 4096),
            'allowed_formats': {'JPEG', 'PNG', 'GIF'}
        }

    def validate_content(self, content: Dict, platform: str) -> List[str]:
        """Validate content for platform-specific requirements."""
        errors = []
        limits = self.platform_limits.get(platform, {})

        # Validate text
        if 'text' in content:
            text_errors = self._validate_text(content['text'], platform)
            errors.extend(text_errors)

        # Validate media
        if 'media' in content:
            media_errors = self._validate_media(content['media'], platform)
            errors.extend(media_errors)

        # Platform-specific validations
        platform_errors = self._platform_specific_validation(content, platform)
        errors.extend(platform_errors)

        return errors

    def _validate_text(self, text: str, platform: str) -> List[str]:
        """Validate text content."""
        errors = []
        limit = self.platform_limits.get(platform, {}).get('text', float('inf'))

        if len(text) > limit:
            errors.append(f"Text exceeds {platform} limit of {limit} characters")

        # Check for empty or whitespace-only content
        if not text.strip():
            errors.append("Text content cannot be empty")

        # Platform specific text validations
        if platform == 'linkedin':
            emoji_count = len(re.findall(r'[\U0001F300-\U0001F999]', text))
            if emoji_count > 3:
                errors.append("Too many emojis for LinkedIn professional tone")

        return errors

    def _validate_media(self, media: Dict, platform: str) -> List[str]:
        """Validate media content."""
        errors = []
        
        if 'image_path' in media and media['image_path']:
            image_errors = self._validate_image(media['image_path'], platform)
            errors.extend(image_errors)

        if 'link_url' in media and media['link_url']:
            link_errors = self._validate_url(media['link_url'])
            errors.extend(link_errors)

        if 'meta_title' in media and len(media['meta_title'] or '') > 100:
            errors.append("Meta title exceeds 100 characters")

        return errors

    def _validate_image(self, image_path: str, platform: str) -> List[str]:
        """Validate image files."""
        errors = []

        if not os.path.exists(image_path):
            return [f"Image file not found: {image_path}"]

        try:
            with Image.open(image_path) as img:
                # Check format
                if img.format not in self.image_requirements['allowed_formats']:
                    errors.append(f"Unsupported image format: {img.format}")

                # Check dimensions
                width, height = img.size
                if width < self.image_requirements['min_dimensions'][0] or \
                   height < self.image_requirements['min_dimensions'][1]:
                    errors.append("Image dimensions too small")
                if width > self.image_requirements['max_dimensions'][0] or \
                   height > self.image_requirements['max_dimensions'][1]:
                    errors.append("Image dimensions too large")

                # Check file size
                file_size = os.path.getsize(image_path)
                if file_size > self.image_requirements['max_size']:
                    errors.append("Image file size too large")

        except Exception as e:
            errors.append(f"Error validating image: {str(e)}")

        return errors

    def _validate_url(self, url: str) -> List[str]:
        """Validate URLs."""
        errors = []
        
        try:
            result = urlparse(url)
            if not all([result.scheme, result.netloc]):
                errors.append("Invalid URL format")
            if result.scheme not in ['http', 'https']:
                errors.append("URL must use HTTP or HTTPS protocol")
        except Exception:
            errors.append("Invalid URL")

        return errors

    def _platform_specific_validation(self, content: Dict, platform: str) -> List[str]:
        """Perform platform-specific validations."""
        errors = []

        if platform == 'instagram':
            if not content.get('media', {}).get('image_path'):
                errors.append("Instagram posts require at least one image")

        elif platform == 'linkedin':
            if content.get('text', '').count('#') > 3:
                errors.append("LinkedIn posts should not have too many hashtags")

        elif platform == 'reddit':
            if content.get('title', '') and len(content['title']) > 300:
                errors.append("Reddit title too long (max 300 characters)")

        return errors