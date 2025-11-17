"""Token counting and truncation utilities for managing LLM context limits."""

import tiktoken
from typing import Optional


class TokenCounter:
    """Handle token counting across different LLM providers."""
    
    PROVIDER_LIMITS = {
        "openai": {
            "gpt-4o-mini": 128000,
            "gpt-4o": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
        },
        "groq": {
            "qwen/qwen3-32b": 32768,
            "llama-3.1-70b-versatile": 131072,
            "llama-3.1-8b-instant": 131072,
            "mixtral-8x7b-32768": 32768,
            "gemma2-9b-it": 8192,
        },
        "claude": {
            "claude-sonnet-4-5": 200000,
            "claude-sonnet-4": 200000,
            "claude-opus-4": 200000,
            "claude-opus-4-1": 200000,
            "claude-3-5-sonnet-20241022": 200000,
            "claude-3-5-sonnet-20240620": 200000,
            "claude-3-opus-20240229": 200000,
            "claude-3-sonnet-20240229": 200000,
            "claude-3-haiku-20240307": 200000,
        }
    }
    
    # Estimated prompt sizes for different commit styles
    PROMPT_SIZES = {
        "commit_conventional": 600,
        "commit_detailed": 850,
        "commit_simple": 500,
    }
    
    def __init__(self, provider: str = "openai"):
        """
        Initialize token counter.
        
        Args:
            provider: LLM provider name
        """
        self.provider = provider
        self._encoding = None
        
    def _get_encoding(self):
        """Get or create tiktoken encoding (lazy loading)."""
        if self._encoding is None:
            try:
                # Please note that this is as a result that cl100k_base is used by GPT-4, GPT-3.5-turbo, and Claude
                self._encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                self._encoding = None
        return self._encoding
    
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text with high precision.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Token count
        """
        encoding = self._get_encoding()
        
        if encoding:
            try:
                return len(encoding.encode(text))
            except Exception:
                pass
        
        return self._estimate_tokens(text)
    
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        Fallback token estimation.
        Conservative estimate: 1 token ≈ 3 characters for code/diffs.
        
        Args:
            text: Text to estimate
            
        Returns:
            Estimated token count
        """
        return len(text) // 3
    
    def get_model_limit(self, model: str) -> int:
        """
        Get total context window size for a model.
        
        Args:
            model: Model name
            
        Returns:
            Total token limit for the model
        """
        provider_limits = self.PROVIDER_LIMITS.get(self.provider, {})
        return provider_limits.get(model, 8000)  # Conservative default
    
    def calculate_max_diff_tokens(
        self, 
        model: str, 
        prompt_style: str = "commit_conventional",
        output_reserve: int = 1000,
        files_list_reserve: int = 100,
        safety_margin: int = 500
    ) -> int:
        """
        Calculate maximum tokens available for diff content.
        
        Args:
            model: Model name
            prompt_style: Commit message style (affects prompt size)
            output_reserve: Tokens to reserve for AI response
            files_list_reserve: Tokens to reserve for file list
            safety_margin: Additional safety buffer
            
        Returns:
            Maximum tokens available for diff content
        """
        total_limit = self.get_model_limit(model)
        prompt_tokens = self.PROMPT_SIZES.get(prompt_style, 700)
        
        max_diff_tokens = (
            total_limit 
            - prompt_tokens 
            - output_reserve 
            - files_list_reserve 
            - safety_margin
        )
        
        return max(max_diff_tokens, 1000)
    
    def truncate_to_limit(
        self, 
        text: str, 
        max_tokens: int, 
        suffix: str = "\n\n... (diff truncated for token limit)"
    ) -> tuple[str, int, int]:
        """
        Truncate text to fit within token limit.
        
        Args:
            text: Text to truncate
            max_tokens: Maximum tokens allowed
            suffix: Text to append when truncated
            
        Returns:
            Tuple of (truncated_text, original_tokens, final_tokens)
        """
        original_tokens = self.count_tokens(text)
        
        if original_tokens <= max_tokens:
            return text, original_tokens, original_tokens
        
        suffix_tokens = self.count_tokens(suffix)
        available_tokens = max_tokens - suffix_tokens
        
        encoding = self._get_encoding()
        
        if encoding:
            try:
                tokens = encoding.encode(text)
                truncated_tokens = tokens[:available_tokens]
                truncated_text = encoding.decode(truncated_tokens)
                result = truncated_text + suffix
                final_tokens = self.count_tokens(result)
                return result, original_tokens, final_tokens
            except Exception:
                pass
        
        chars_per_token = len(text) / original_tokens if original_tokens > 0 else 3
        max_chars = int(available_tokens * chars_per_token)
        
        truncated_text = text[:max_chars] + suffix
        final_tokens = self.count_tokens(truncated_text)
        
        return truncated_text, original_tokens, final_tokens
    
    def truncate_intelligently(
        self,
        diff_text: str,
        max_tokens: int,
        preserve_start: bool = True
    ) -> tuple[str, int, int]:
        """
        Intelligently truncate diff, preserving important context.
        
        Args:
            diff_text: Git diff text
            max_tokens: Maximum tokens allowed
            preserve_start: If True, keep beginning; if False, keep end
            
        Returns:
            Tuple of (truncated_text, original_tokens, final_tokens)
        """
        original_tokens = self.count_tokens(diff_text)
        
        if original_tokens <= max_tokens:
            return diff_text, original_tokens, original_tokens
        
        file_diffs = diff_text.split('diff --git')
        
        if len(file_diffs) <= 1:
            suffix = "\n\n... (diff truncated - too large for context window)"
            return self.truncate_to_limit(diff_text, max_tokens, suffix)
        
        result_parts = ['']  
        current_tokens = 0
        suffix = "\n\n... (remaining files truncated - too large for context window)"
        suffix_tokens = self.count_tokens(suffix)
        
        file_parts = file_diffs[1:] if file_diffs[0] == '' else file_diffs
        
        for i, file_diff in enumerate(file_parts):
            full_diff = 'diff --git' + file_diff
            file_tokens = self.count_tokens(full_diff)
            
            if current_tokens + file_tokens + suffix_tokens > max_tokens:
                result_parts.append(suffix)
                break
            
            result_parts.append(file_diff)
            current_tokens += file_tokens
        else:
            result_parts = file_diffs
        
        result = 'diff --git'.join(result_parts) if result_parts[0] == '' else '\n'.join(result_parts)
        final_tokens = self.count_tokens(result)
        
        return result, original_tokens, final_tokens