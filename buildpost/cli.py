"""Command-line interface for BuildPost."""

import sys
from datetime import datetime, timezone, timedelta
import click
import pyperclip

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from buildpost.core.git_parser import GitParser, InvalidGitRepositoryError
from buildpost.core.ai_service import AIService
from buildpost.core.prompt_engine import PromptEngine
from buildpost.utils.config import Config
from buildpost.utils.formatters import format_post
from buildpost.utils.token_resolver import TokenCounter

console = Console()


@click.group(invoke_without_command=True)
@click.option("--commit", "-c", help="Specific commit hash to use")
@click.option("--range", "-r", help="Commit range (e.g., HEAD~5..HEAD)")
@click.option("--style", "-s", help="Prompt style (casual, professional, etc.)")
@click.option("--platform", "-p", help="Target platform (twitter, linkedin, etc.)")
@click.option("--no-hashtags", is_flag=True, help="Exclude hashtags")
@click.option("--no-copy", is_flag=True, help="Do not copy to clipboard")
@click.option("--api-key", help="LLM API key (overrides config)")
@click.option(
    "--provider",
    type=click.Choice(AIService.supported_providers()),
    help="LLM provider to use (openai, groq)",
)
@click.pass_context
def cli(ctx, commit, range, style, platform, no_hashtags, no_copy, api_key, provider):
    """BuildPost - Turn your git commits into social media posts using AI."""
    # If a subcommand is being called, don't run the main logic
    if ctx.invoked_subcommand is not None:
        return

    try:
        # Load configuration
        config = Config()
        active_provider = provider or config.get_provider()

        if active_provider not in AIService.supported_providers():
            console.print(
                f"[bold red]Error:[/bold red] Unsupported provider '{active_provider}'. "
                f"Supported providers: {', '.join(AIService.supported_providers())}"
            )
            sys.exit(1)

        # Get API key
        if not api_key:
            api_key = config.get_api_key(active_provider)

        if not api_key:
            provider_info = AIService.get_provider_info(active_provider)
            env_var = provider_info.get("env_var", "API_KEY")
            signup_url = provider_info.get("signup_url")
            display_name = provider_info.get("display_name", active_provider)

            console.print(
                f"[bold red]Error:[/bold red] No API key found for {display_name}.\n"
            )
            if signup_url:
                console.print(f"Get your API key at: {signup_url}\n")
            console.print(
                "Then set it using one of these methods:\n"
                f"  1. buildpost config set-key --provider {active_provider} YOUR_API_KEY\n"
                f"  2. export {env_var}=YOUR_API_KEY\n"
                "  3. buildpost --api-key YOUR_API_KEY"
            )
            sys.exit(1)

        # Initialize services
        git_parser = GitParser()
        ai_service = AIService(
            provider=active_provider,
            api_key=api_key,
            model=config.get_model(active_provider),
        )
        prompt_engine = PromptEngine(prompts_file=str(config.get_prompts_file()))

        # Get commit info
        if range:
            console.print(
                "[yellow]Note:[/yellow] Range mode will summarize multiple commits.\n"
            )
            commits = git_parser.get_commit_range(range)
            if not commits:
                console.print("[bold red]Error:[/bold red] No commits found in range.")
                sys.exit(1)
            # Use the first commit for now (future: summarize all)
            commit_info = commits[0]
        elif commit:
            commit_info = git_parser.get_commit(commit)
        else:
            commit_info = git_parser.get_latest_commit()

        # Show commit info
        console.print(f"\n[bold]Commit:[/bold] {commit_info.short_hash}")
        console.print(f"[bold]Message:[/bold] {commit_info.message}")
        console.print(f"[bold]Files:[/bold] {len(commit_info.files_changed)} changed\n")

        # Get style and platform
        prompt_style = style or config.get_default_prompt()
        target_platform = platform or config.get_default_platform()

        # Render prompt
        try:
            rendered_prompt = prompt_engine.render_prompt(
                prompt_style, commit_info.to_dict()
            )
        except KeyError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            console.print("\nAvailable prompts:")
            for p in prompt_engine.list_prompts():
                console.print(f"  • {p['name']}: {p['description']}")
            sys.exit(1)

        # Generate post
        with console.status("[bold green]Generating post with AI...", spinner="dots"):
            try:
                generated_content = ai_service.generate_post(
                    system_prompt=rendered_prompt["system"],
                    user_prompt=rendered_prompt["user"],
                    temperature=config.get_temperature(),
                    max_tokens=config.get_max_tokens(),
                )
            except Exception as e:
                console.print(f"[bold red]Error generating post:[/bold red] {e}")
                sys.exit(1)

        # Get platform config and hashtags
        try:
            platform_config = prompt_engine.get_platform(target_platform)
            hashtags = None

            if not no_hashtags and config.should_include_hashtags():
                hashtags = prompt_engine.get_platform_hashtags(target_platform)
                max_tags = prompt_engine.get_max_hashtags()
                hashtags = hashtags[:max_tags] if hashtags else None

        except KeyError:
            console.print(
                f"[yellow]Warning:[/yellow] Unknown platform '{target_platform}', using generic format."
            )
            platform_config = {"max_length": 500}
            hashtags = None

        # Format post
        formatted_post = format_post(
            generated_content, target_platform, platform_config, hashtags
        )

        # Display the post
        console.print("\n" + "=" * 60)
        console.print(
            Panel(
                formatted_post,
                title=f"[bold green]Generated Post[/bold green] ({target_platform} | {prompt_style})",
                border_style="green",
            )
        )
        console.print("=" * 60 + "\n")

        # Show character count
        char_count = len(formatted_post)
        max_length = platform_config.get("max_length", 500)
        count_color = "green" if char_count <= max_length else "red"
        console.print(
            f"[{count_color}]Characters: {char_count}/{max_length}[/{count_color}]\n"
        )

        # Copy to clipboard
        if not no_copy and config.should_copy_to_clipboard():
            try:
                pyperclip.copy(formatted_post)
                console.print("[bold green]✓[/bold green] Copied to clipboard!")
            except Exception:
                console.print("[yellow]Could not copy to clipboard[/yellow]")

    except InvalidGitRepositoryError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        if "--debug" in sys.argv:
            raise
        sys.exit(1)


@cli.group()
def config():
    """Manage BuildPost configuration."""
    pass


@config.command("show")
def config_show():
    """Show current configuration."""
    cfg = Config()
    console.print("\n[bold]Current Configuration:[/bold]\n")
    console.print(cfg.show())


@config.command("set-key")
@click.argument("api_key")
@click.option(
    "--provider",
    "-p",
    type=click.Choice(AIService.supported_providers()),
    help="LLM provider to associate with this key",
)
def config_set_key(api_key, provider):
    """Set an API key for the selected LLM provider."""
    cfg = Config()
    target_provider = provider or cfg.get_provider()

    if not AIService.validate_api_key(api_key, target_provider):
        console.print(
            "[bold yellow]Warning:[/bold yellow] API key format looks unusual for "
            f"provider '{target_provider}'."
        )

    cfg.set_api_key(api_key, provider=target_provider)
    provider_name = AIService.get_provider_info(target_provider).get(
        "display_name", target_provider
    )
    console.print(f"[bold green]✓[/bold green] API key saved for {provider_name}!")


@config.command("set-provider")
@click.argument("provider", type=click.Choice(AIService.supported_providers()))
@click.option("--model", help="Optional default model name to use for this provider")
def config_set_provider(provider, model):
    """Switch the active LLM provider."""
    cfg = Config()
    cfg.set_provider(provider)
    if model:
        cfg.set_model(provider, model)
    provider_name = AIService.get_provider_info(provider).get("display_name", provider)
    console.print(
        f"[bold green]✓[/bold green] Active provider set to {provider_name} ({provider})."
    )
    if model:
        console.print(f"[green]-[/green] Default model updated to '{model}'.")

    if not cfg.get_api_key(provider):
        info = AIService.get_provider_info(provider)
        env_var = info.get("env_var", "API_KEY")
        console.print(
            f"[yellow]Reminder:[/yellow] Configure an API key for {provider_name}:\n"
            f"  buildpost config set-key --provider {provider} YOUR_API_KEY\n"
            f"  or set {env_var}=YOUR_API_KEY"
        )


@config.command("reset")
def config_reset():
    """Reset configuration to defaults."""
    cfg = Config()
    cfg.reset()
    console.print("[bold green]✓[/bold green] Configuration reset to defaults!")


@config.command("init")
def config_init():
    """Initialize BuildPost configuration."""
    cfg = Config()
    cfg.init_prompts_file()
    console.print("[bold green]✓[/bold green] Configuration initialized!")
    console.print(f"Config directory: {cfg.config_dir}")
    console.print(f"Prompts file: {cfg.prompts_file}")


@cli.group()
def prompts():
    """Manage prompt templates."""
    pass


@prompts.command("list")
def prompts_list():
    """List available prompt templates."""
    cfg = Config()
    prompt_engine = PromptEngine(prompts_file=str(cfg.get_prompts_file()))

    table = Table(title="Available Prompt Templates")
    table.add_column("Name", style="cyan")
    table.add_column("Display Name", style="green")
    table.add_column("Description")

    for prompt in prompt_engine.list_prompts():
        table.add_row(prompt["name"], prompt["display_name"], prompt["description"])

    console.print("\n")
    console.print(table)
    console.print("\n")


@prompts.command("edit")
def prompts_edit():
    """Open prompts file in default editor."""
    import os
    import subprocess

    cfg = Config()
    prompts_file = cfg.get_prompts_file()

    editor = os.getenv("EDITOR", "nano")

    try:
        subprocess.run([editor, str(prompts_file)])
        console.print("[bold green]✓[/bold green] Prompts file edited!")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] Could not open editor: {e}")
        console.print(f"Edit manually: {prompts_file}")


@cli.group()
def platforms():
    """Manage platform configurations."""
    pass


@platforms.command("list")
def platforms_list():
    """List available platforms."""
    cfg = Config()
    prompt_engine = PromptEngine(prompts_file=str(cfg.get_prompts_file()))

    table = Table(title="Available Platforms")
    table.add_column("Name", style="cyan")
    table.add_column("Display Name", style="green")
    table.add_column("Max Length", style="yellow")

    for platform in prompt_engine.list_platforms():
        table.add_row(
            platform["name"], platform["display_name"], str(platform["max_length"])
        )

    console.print("\n")
    console.print(table)
    console.print("\n")


@cli.command()
def version():
    """Show BuildPost version."""
    console.print("[bold]BuildPost[/bold] v0.1.1")
    console.print("Turn your git commits into social media posts using AI")


def _build_changelog_context(commits, range_spec: str) -> dict:
    """Build template context for changelog generation."""
    commit_lines = []
    unique_files = set()
    total_insertions = 0
    total_deletions = 0

    for commit in commits:
        date = commit.date.split(" ")[0]
        file_count = len(commit.files_changed)
        unique_files.update(commit.files_changed)
        total_insertions += commit.insertions
        total_deletions += commit.deletions

        delta_parts = []
        if commit.insertions:
            delta_parts.append(f"+{commit.insertions}")
        if commit.deletions:
            delta_parts.append(f"-{commit.deletions}")
        delta = " ".join(delta_parts) if delta_parts else "0"

        commit_lines.append(
            f"- {date} {commit.short_hash} {commit.message} "
            f"({file_count} files, {delta})"
        )

    if commits:
        newest = commits[0].date.split(" ")[0]
        oldest = commits[-1].date.split(" ")[0]
        date_range = f"{oldest} to {newest}"
    else:
        date_range = "No commits found"

    return {
        "date_range": date_range,
        "range_spec": range_spec,
        "commit_count": len(commits),
        "unique_files_count": len(unique_files),
        "total_insertions": total_insertions,
        "total_deletions": total_deletions,
        "commits_list": "\n".join(commit_lines) if commit_lines else "No commits.",
    }


@cli.command()
@click.option("--since", help="Start date/time (e.g., 2026-01-01 or '7 days ago')")
@click.option("--until", help="End date/time (e.g., 2026-01-07 or 'now')")
@click.option(
    "--days",
    type=int,
    default=7,
    show_default=True,
    help="Number of days to look back when --since isn't set",
)
@click.option("--range", "-r", "rev_range", help="Git revision range (e.g., main..HEAD)")
@click.option("--style", "-s", default="weekly_changelog", help="Prompt style to use")
@click.option("--output", "-o", type=click.Path(dir_okay=False), help="Write to a file")
@click.option("--no-copy", is_flag=True, help="Do not copy to clipboard")
@click.option("--api-key", help="LLM API key (overrides config)")
@click.option(
    "--provider",
    type=click.Choice(AIService.supported_providers()),
    help="LLM provider to use (openai, groq, claude)",
)
@click.option("--max-tokens", type=int, default=None, help="Maximum tokens for the output")
def changelog(since, until, days, rev_range, style, output, no_copy, api_key, provider, max_tokens):
    """Generate a weekly changelog from recent commits."""
    try:
        config = Config()
        ai_service, prompt_engine, _ = _setup_ai_services(api_key, provider, config)
        git_parser = GitParser()

        if rev_range:
            commits = git_parser.get_commit_range(rev_range)
            range_spec = f"range {rev_range}"
        else:
            if not since:
                since_date = datetime.now(timezone.utc) - timedelta(days=days)
                since = since_date.strftime("%Y-%m-%d %H:%M:%S")
            commits = git_parser.get_commits_by_date(since=since, until=until)
            range_spec = f"since {since}" if not until else f"{since} to {until}"

        if not commits:
            console.print("[bold yellow]No commits found for that range.[/bold yellow]")
            sys.exit(0)

        context = _build_changelog_context(commits, range_spec)

        try:
            rendered_prompt = prompt_engine.render_prompt(style, context)
        except KeyError:
            console.print(
                f"[yellow]Prompt '{style}' not found. Using built-in changelog template.[/yellow]"
            )
            fallback_system = (
                "You are a senior software engineer who writes concise, "
                "useful weekly changelogs for stakeholders and developers."
            )
            fallback_template = (
                "Create a weekly changelog from the commits below.\n\n"
                "Date Range: {date_range}\n"
                "Range Spec: {range_spec}\n"
                "Total Commits: {commit_count}\n"
                "Unique Files: {unique_files_count}\n"
                "Total Changes: +{total_insertions}/-{total_deletions}\n\n"
                "Commits:\n{commits_list}\n\n"
                "Write a changelog with:\n"
                "- A short summary paragraph\n"
                "- 3-6 bullet highlights grouped by theme\n"
                "- A concise list of notable commits (if needed)\n"
                "- Keep it under 350 words\n"
                "- Use Markdown formatting\n"
            )
            rendered_prompt = {
                "system": fallback_system,
                "user": fallback_template.format(**context),
                "name": "weekly_changelog_fallback",
            }

        with console.status("[bold green]Generating changelog with AI...", spinner="dots"):
            try:
                generated = ai_service.generate_post(
                    system_prompt=rendered_prompt["system"],
                    user_prompt=rendered_prompt["user"],
                    max_tokens=max_tokens or config.get_max_tokens(),
                    temperature=config.get_temperature(),
                )
            except Exception as e:
                console.print(f"[bold red]Error generating changelog:[/bold red] {e}")
                sys.exit(1)

        console.print("\n" + "=" * 60)
        console.print(
            Panel(
                Markdown(generated),
                title=f"[bold green]Weekly Changelog[/bold green] ({style})",
                border_style="green",
            )
        )
        console.print("=" * 60 + "\n")

        if output:
            try:
                with open(output, "w", encoding="utf-8") as f:
                    f.write(generated)
                console.print(f"[bold green]✓[/bold green] Wrote changelog to {output}")
            except Exception as e:
                console.print(f"[bold red]Error writing file:[/bold red] {e}")

        if not no_copy and config.should_copy_to_clipboard():
            try:
                pyperclip.copy(generated)
                console.print("[bold green]✓[/bold green] Copied to clipboard!")
            except Exception:
                console.print("[yellow]Could not copy to clipboard[/yellow]")

    except InvalidGitRepositoryError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        if "--debug" in sys.argv:
            raise
        sys.exit(1)


def _clean_ai_output(raw_output: str) -> str:
    """Smart extraction of commit message from AI output with thinking process."""
    import re
    
    if not raw_output:
        return ""
    
    # Strategy 0: Look for commit message after specific phrases
    commit_indicators = [
        r'(?:the commit message (?:would be|should be|is)|so the commit message would be|commit message:|message:)\s*:?\s*\n?\s*([^\n]+)',
        r'(?:would be|should be|is):\s*\n?\s*([a-z]+(?:\([^)]+\))?:\s*[^\n]+)',
        r'^([a-z]+(?:\([^)]+\))?:\s*[^\n]+)$',
    ]

    for pattern in commit_indicators:
        matches = re.findall(pattern, raw_output, re.MULTILINE | re.IGNORECASE)
        if matches:
            commit_msg = matches[0].strip()
            if len(commit_msg) > 10 and ':' in commit_msg:
                return commit_msg
    
    # Strategy 1: Remove thinking tags first
    cleaned = raw_output

    thinking_patterns = [
        r'<think>.*?</think>',
        r'<thinking>.*?</thinking>',
        r'<analysis>.*?</analysis>',
        r'<thought>.*?</thought>',
    ]
    
    for pattern in thinking_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    
    # Strategy 2: Extract multi-line commit message (for detailed commits)
    lines = cleaned.split('\n')
    commit_start_idx = -1
    
    # Find where the actual commit message starts
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        # Skip obvious analysis/thinking lines
        skip_patterns = [
            r'^(okay|let me|looking at|based on|i can see|this appears|it seems|the changes|analyzing|from the diff|the diff shows|that fits|the conventional|putting it all together)',
            r'^(maybe|probably|also|since|but|however|therefore|thus|hence|so)',
            r'characters?\.|spec\.|good\.|needed\.|similar\.',
            r'(should be|would be|could be|might be)',
        ]
        
        is_analysis = False
        for pattern in skip_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                is_analysis = True
                break
        
        if not is_analysis:
            # Check if this looks like a commit message start
            if (re.match(r'^[A-Z][a-z]', line) and len(line) < 72) or \
               re.match(r'^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(\([^)]+\))?:', line, re.IGNORECASE):
                commit_start_idx = i
                break
    
    # Strategy 3: Extract the commit message from start index
    if commit_start_idx >= 0:
        commit_lines = []
        for i in range(commit_start_idx, len(lines)):
            line = lines[i].strip()
            
            # Stop at obvious analysis continuation
            if re.search(r'^(the feature|this|it|also note|avoid the|focus on|make sure)', line, re.IGNORECASE):
                break
                
            # Include the line if it's substantial
            if line:
                commit_lines.append(line)
            elif commit_lines:  # Empty line after we've started collecting
                commit_lines.append('')
        
        if commit_lines:
            # Clean up trailing empty lines
            while commit_lines and not commit_lines[-1]:
                commit_lines.pop()
            
            if commit_lines:
                return '\n'.join(commit_lines)
    
    # Strategy 4: Look for conventional commit patterns (fallback for simple commits)
    conventional_pattern = r'^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(\([^)]+\))?\s*:\s*.+$'
    
    for line in lines:
        line = line.strip()
        if re.match(conventional_pattern, line, re.IGNORECASE):
            return line
    
    # Strategy 5: Find the most commit-like single line
    potential_commits = []
    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue
            
        # Skip obvious analysis text
        skip_patterns = [
            r'^(okay|let me|looking at|based on|i can see|this appears|it seems|the changes|analyzing|from the diff|the diff shows|that fits|the conventional)',
            r'^(here\'s|here is|the commit message|commit message|message)',
            r'characters?\.|spec\.|good\.|needed\.',
        ]
        
        skip_line = False
        for pattern in skip_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                skip_line = True
                break
        
        if not skip_line:
            # Score the line based on commit-like characteristics
            score = 0
            if re.match(r'^[A-Z][a-z]', line):  # Starts with capital letter
                score += 5
            if re.match(r'^[a-z]+(\([^)]+\))?:', line):  # Conventional format
                score += 10
            if len(line) < 72:  # Good commit length
                score += 3
            if not line.endswith('.'):  # No period at end
                score += 2
            if any(word in line.lower() for word in ['add', 'fix', 'update', 'remove', 'refactor', 'implement', 'create']):
                score += 3
                
            potential_commits.append((score, line))
    
    if potential_commits:
        # Return the highest scoring commit-like line
        potential_commits.sort(key=lambda x: x[0], reverse=True)
        return potential_commits[0][1]
    
    # Fallback: return first substantial line
    for line in lines:
        line = line.strip()
        if line and len(line) > 10 and not line.lower().startswith(('okay', 'let me', 'looking', 'based')):
            return line
    
    return raw_output.strip()


def _setup_ai_services(api_key, provider, config):
    """
    Setup AI services with proper error handling. Reuses logic from main CLI.
    
    Returns:
        Tuple of (ai_service, prompt_engine, active_provider)
    """
    active_provider = provider or config.get_provider()

    if active_provider not in AIService.supported_providers():
        console.print(
            f"[bold red]Error:[/bold red] Unsupported provider '{active_provider}'. "
            f"Supported providers: {', '.join(AIService.supported_providers())}"
        )
        sys.exit(1)

    # Get API key
    if not api_key:
        api_key = config.get_api_key(active_provider)

    if not api_key:
        provider_info = AIService.get_provider_info(active_provider)
        env_var = provider_info.get("env_var", "API_KEY")
        signup_url = provider_info.get("signup_url")
        display_name = provider_info.get("display_name", active_provider)

        console.print(
            f"[bold red]Error:[/bold red] No API key found for {display_name}.\n"
        )
        if signup_url:
            console.print(f"Get your API key at: {signup_url}\n")
        console.print(
            "Then set it using one of these methods:\n"
            f"  1. buildpost config set-key --provider {active_provider} YOUR_API_KEY\n"
            f"  2. export {env_var}=YOUR_API_KEY\n"
            "  3. buildpost commit --api-key YOUR_API_KEY"
        )
        sys.exit(1)

    # Initialize services
    ai_service = AIService(
        provider=active_provider,
        api_key=api_key,
        model=config.get_model(active_provider),
    )
    prompt_engine = PromptEngine(prompts_file=str(config.get_prompts_file()))
    
    return ai_service, prompt_engine, active_provider

@cli.command()
@click.option("--style", "-s", default="commit_conventional", 
              help="Commit message style")
@click.option("--stage-all", "-a", is_flag=True, 
              help="Stage all changes before committing")
@click.option("--no-commit", is_flag=True, 
              help="Generate message only, don't commit")
@click.option("--api-key", help="LLM API key (overrides config)")
@click.option("--provider", type=click.Choice(AIService.supported_providers()),
    help="LLM provider to use (openai, groq, claude)",
)
@click.option("--max-tokens", type=int, default=None,
    help="Maximum tokens for diff content (auto-calculated if not set)"
)
@click.option("--output-tokens", type=int, default=1500,
    help="Tokens reserved for AI response (default: 1500)"
)
def commit(style, stage_all, no_commit, api_key, provider, max_tokens, output_tokens):
    """Generate AI-powered commit message from current changes and commit."""
    try:
        config = Config()
        ai_service, prompt_engine, active_provider = _setup_ai_services(api_key, provider, config)
        
        git_parser = GitParser()
        changes_summary = git_parser.get_changes_summary()
        
        if not changes_summary["has_staged"] and not changes_summary["has_unstaged"] and not changes_summary["has_untracked"]:
            console.print("[yellow]No changes to commit.[/yellow]")
            sys.exit(0)

        if stage_all:
            console.print("[yellow]Staging all changes...[/yellow]")
            git_parser.stage_all_changes()
            changes_summary = git_parser.get_changes_summary()

        if changes_summary["has_staged"]:
            console.print(f"\n[bold]Staged files ({len(changes_summary['staged_files'])}):[/bold]")
            for file in changes_summary["staged_files"][:10]:
                console.print(f"  [green]✓[/green] {file}")
            if len(changes_summary["staged_files"]) > 10:
                console.print(f"  ... and {len(changes_summary['staged_files']) - 10} more")
        else:
            console.print("\n[bold red]No staged changes to commit.[/bold red]")
            console.print("Use [cyan]--stage-all[/cyan] to stage all changes, or stage files manually with [cyan]git add[/cyan]")
            sys.exit(1)

        diff_text = git_parser.get_all_changes_diff()
        if not diff_text:
            console.print("[bold red]Error:[/bold red] Could not get diff")
            sys.exit(1)

        token_counter = TokenCounter(provider=active_provider)
        
        try:
            if max_tokens is None:
                max_tokens = token_counter.calculate_max_diff_tokens(
                    model=ai_service.model_name,
                    prompt_style=style,
                    output_reserve=output_tokens
                )
                
                console.print(
                    f"[dim]Token allocation - Diff: {max_tokens:,} | "
                    f"Output: {output_tokens:,}[/dim]"
                )
        except ValueError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            sys.exit(1)
        
        diff_text, original_tokens, final_tokens = token_counter.truncate_intelligently(
            diff_text, 
            max_tokens
        )
        
        if original_tokens > max_tokens:
            console.print(
                f"[yellow]⚠ Diff truncated:[/yellow] {original_tokens:,} → {final_tokens:,} tokens"
            )
        else:
            console.print(f"[dim]Diff size: {original_tokens:,} tokens[/dim]")

        context = {
            "files_changed": ", ".join(changes_summary["staged_files"]),
            "diff_content": diff_text,
        }

        try:
            rendered_prompt = prompt_engine.render_prompt(style, context)
        except KeyError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            sys.exit(1)

        with console.status("[bold green]Generating commit message with AI...", spinner="dots"):
            try:
                raw_commit_message = ai_service.generate_post(
                    system_prompt=rendered_prompt["system"],
                    user_prompt=rendered_prompt["user"],
                    max_tokens=output_tokens, 
                    temperature=config.get_temperature(),
                )
            except Exception as e:
                console.print(f"[bold red]Error generating commit message:[/bold red] {e}")
                sys.exit(1)
        
        commit_message = _clean_ai_output(raw_commit_message)

        console.print("\n" + "=" * 60)
        console.print(
            Panel(
                commit_message,
                title=f"[bold green]Generated Commit Message[/bold green] ({style})",
                border_style="green",
            )
        )
        console.print("=" * 60 + "\n")

        if no_commit:
            console.print("[yellow]Message generated. Use without --no-commit to actually commit.[/yellow]")
            sys.exit(0)

        console.print("[bold]Do you want to commit with this message?[/bold]")
        console.print("  [green]y[/green] - Yes, commit now")
        console.print("  [yellow]e[/yellow] - Edit message")
        console.print("  [red]n[/red] - Cancel")
        
        choice = click.prompt("\nChoice", type=click.Choice(['y', 'e', 'n']), default='y')

        if choice == 'n':
            console.print("[yellow]Commit cancelled.[/yellow]")
            sys.exit(0)
        
        if choice == 'e':
            edited_message = click.edit(commit_message)
            if edited_message:
                commit_message = edited_message.strip()
            else:
                console.print("[yellow]Commit cancelled (no message provided).[/yellow]")
                sys.exit(0)

        try:
            commit_hash = git_parser.commit_changes(commit_message)
            console.print(f"\n[bold green]✓[/bold green] Committed successfully!")
            console.print(f"[bold]Commit hash:[/bold] {commit_hash[:7]}")
        except Exception as e:
            console.print(f"[bold red]Error committing:[/bold red] {e}")
            sys.exit(1)

    except InvalidGitRepositoryError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        if "--debug" in sys.argv:
            raise
        sys.exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
