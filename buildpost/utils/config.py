"""Configuration management for BuildPost."""

import copy
import os
import yaml
from pathlib import Path
from typing import Dict, Optional


class Config:
    """Manage BuildPost configuration."""

    DEFAULT_PROVIDER = "openai"
    DEFAULT_MODELS = {
        "openai": "gpt-4o-mini",
        "groq": "qwen/qwen3-32b",
        "claude": "claude-sonnet-4-5",
        "openrouter": "openai/gpt-4o-mini"
    }
    PROVIDER_ENV_VARS = {
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY"
    }

    def __init__(self):
        """Initialize configuration manager."""
        self.config_dir = Path.home() / ".buildpost"
        self.config_file = self.config_dir / "config.yaml"
        self.prompts_file = self.config_dir / "prompts.yaml"

        # Create config directory if it doesn't exist
        self.config_dir.mkdir(exist_ok=True)

        # Load or create config
        self.data = self._load_config()
        self._ensure_defaults()

    def _load_config(self) -> Dict:
        """
        Load configuration from file.

        Returns:
            Configuration dictionary
        """
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except yaml.YAMLError:
                return self._get_default_config()
        return self._get_default_config()

    def _merge_with_defaults(self, defaults: Dict, current: Optional[Dict]) -> Dict:
        """
        Merge user configuration with defaults without losing user values.

        Args:
            defaults: Default configuration structure
            current: User configuration structure

        Returns:
            Combined configuration dictionary
        """
        if not isinstance(defaults, dict):
            return current if current is not None else defaults

        merged = dict(defaults)
        if isinstance(current, dict):
            for key, value in current.items():
                if key in merged:
                    merged[key] = self._merge_with_defaults(merged[key], value)
                else:
                    merged[key] = value
        return merged

    def _ensure_defaults(self):
        """
        Ensure the configuration contains all default keys.
        """
        defaults = self._get_default_config()
        merged = self._merge_with_defaults(defaults, self.data)
        if merged != self.data:
            self.data = merged
            self.save()
        else:
            self.data = merged

    def _get_default_config(self) -> Dict:
        """
        Get default configuration.

        Returns:
            Default config dictionary
        """
        return {
            "api": {
                "provider": self.DEFAULT_PROVIDER,
                "model": self.DEFAULT_MODELS[self.DEFAULT_PROVIDER],
                "models": self.DEFAULT_MODELS.copy(),
                "api_key": None,
                "api_keys": {},
            },
            "defaults": {
                "prompt_style": "casual",
                "platform": "twitter",
                "include_hashtags": True,
                "copy_to_clipboard": True,
            },
            "generation": {
                "temperature": 0.7,
                "max_tokens": 500,
            },
        }

    def save(self):
        """Save configuration to file."""
        with open(self.config_file, "w", encoding="utf-8") as f:
            yaml.dump(self.data, f, default_flow_style=False)

    def get(self, key: str, default=None):
        """
        Get a configuration value.

        Args:
            key: Config key in dot notation (e.g., 'api.model')
            default: Default value if key not found

        Returns:
            Configuration value
        """
        keys = key.split(".")
        value = self.data

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    def set(self, key: str, value):
        """
        Set a configuration value.

        Args:
            key: Config key in dot notation (e.g., 'api.model')
            value: Value to set
        """
        keys = key.split(".")
        data = self.data

        # Navigate to the nested key
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]

        # Set the value
        data[keys[-1]] = value
        self.save()

    def get_api_key(self, provider: Optional[str] = None) -> Optional[str]:
        """
        Get API key from config or environment.

        Returns:
            API key or None
        """
        provider = provider or self.get_provider()
        api_keys = self.get("api.api_keys", {})

        if isinstance(api_keys, dict):
            api_key = api_keys.get(provider)
            if api_key:
                return api_key

        # Backwards compatibility with legacy single api_key field
        legacy_key = self.get("api.api_key")
        if legacy_key and provider == self.get_provider():
            return legacy_key

        # Fall back to provider-specific environment variable
        env_var = self.PROVIDER_ENV_VARS.get(provider)
        if env_var:
            return os.getenv(env_var)

        return None

    def set_api_key(self, api_key: str, provider: Optional[str] = None):
        """
        Save API key to config.

        Args:
            api_key: API key to save
        """
        provider = provider or self.get_provider()
        data = self.data.setdefault("api", {})
        api_keys = data.setdefault("api_keys", {})
        api_keys[provider] = api_key
        # Maintain legacy key for backwards compatibility with defaults
        if provider == self.get_provider():
            data["api_key"] = api_key
        self.save()

    def get_default_prompt(self) -> str:
        """Get default prompt style."""
        return self.get("defaults.prompt_style", "casual")

    def get_default_platform(self) -> str:
        """Get default platform."""
        return self.get("defaults.platform", "twitter")

    def should_include_hashtags(self) -> bool:
        """Check if hashtags should be included."""
        return self.get("defaults.include_hashtags", True)

    def should_copy_to_clipboard(self) -> bool:
        """Check if posts should be copied to clipboard."""
        return self.get("defaults.copy_to_clipboard", True)

    def get_model(self, provider: Optional[str] = None) -> str:
        """Get AI model name."""
        provider = provider or self.get_provider()
        models = self.get("api.models", {})

        if isinstance(models, dict):
            model = models.get(provider)
            if model:
                return model

        legacy_model = self.get("api.model")
        if legacy_model and provider == self.get_provider():
            return legacy_model

        return self.DEFAULT_MODELS.get(
            provider, self.DEFAULT_MODELS[self.DEFAULT_PROVIDER]
        )

    def set_model(self, provider: str, model: str):
        """
        Set the default model for a provider.

        Args:
            provider: Provider identifier
            model: Model name
        """
        data = self.data.setdefault("api", {})
        models = data.setdefault("models", {})
        models[provider] = model
        if provider == self.get_provider():
            data["model"] = model
        self.save()

    def get_provider(self) -> str:
        """Get the configured provider."""
        return self.get("api.provider", self.DEFAULT_PROVIDER)

    def set_provider(self, provider: str):
        """Set the active provider."""
        self.set("api.provider", provider)
        # Keep legacy single-model field aligned for backwards compatibility
        model = self.get_model(provider)
        self.set("api.model", model)

    def get_temperature(self) -> float:
        """Get generation temperature."""
        return self.get("generation.temperature", 0.7)

    def get_max_tokens(self) -> int:
        """Get max tokens for generation."""
        return self.get("generation.max_tokens", 500)

    def init_prompts_file(self):
        """
        Copy default prompts.yaml to user config directory.

        Returns:
            Path to created prompts file
        """
        if self.prompts_file.exists():
            return self.prompts_file

        # Copy from package templates
        package_dir = Path(__file__).parent.parent
        default_prompts = package_dir / "templates" / "prompts.yaml"

        if default_prompts.exists():
            import shutil

            shutil.copy(default_prompts, self.prompts_file)
        else:
            # Create a minimal prompts file
            minimal_prompts = {
                "prompts": {
                    "casual": {
                        "name": "Casual",
                        "description": "Casual and friendly",
                        "system": "You are a friendly developer.",
                        "template": "Create a casual post about: {commit_message}",
                    }
                },
                "platforms": {
                    "twitter": {
                        "name": "Twitter/X",
                        "max_length": 280,
                    }
                },
                "config": {
                    "default_prompt": "casual",
                    "default_platform": "twitter",
                },
            }

            with open(self.prompts_file, "w", encoding="utf-8") as f:
                yaml.dump(minimal_prompts, f, default_flow_style=False)

        return self.prompts_file

    def get_prompts_file(self) -> Path:
        """
        Get path to prompts file.

        Returns:
            Path to prompts.yaml
        """
        if not self.prompts_file.exists():
            self.init_prompts_file()

        return self.prompts_file

    def reset(self):
        """Reset configuration to defaults."""
        self.data = self._get_default_config()
        self.save()

    def show(self) -> str:
        """
        Get configuration as formatted string.

        Returns:
            YAML formatted config
        """
        display_data = copy.deepcopy(self.data)
        api_section = display_data.get("api", {})

        api_key = api_section.get("api_key")
        if api_key:
            api_section["api_key"] = (
                f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
            )

        api_keys = api_section.get("api_keys", {})
        if isinstance(api_keys, dict):
            masked_keys = {}
            for provider, key in api_keys.items():
                if not key:
                    masked_keys[provider] = None
                elif len(key) <= 8:
                    masked_keys[provider] = "***"
                else:
                    masked_keys[provider] = f"{key[:4]}...{key[-4:]}"
            api_section["api_keys"] = masked_keys

        return yaml.dump(display_data, default_flow_style=False)
