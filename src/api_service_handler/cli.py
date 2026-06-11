"""Command Line Interface for the API Service Handler."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from functools import wraps
from typing import Any, Optional

import click
from rich.console import Console
from rich.table import Table

from .client import APIServiceHandler
from .config import get_config_from_env
from .enums import Provider, KeyStatus, Environment

console = Console()

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@click.group()
@click.pass_context
def cli(ctx: click.Context):
    """API Service Handler (ash) CLI.
    
    Enterprise API key management: rotation, rate-limiting, usage tracking.
    """
    # Load configuration from environment
    config = get_config_from_env()
    ctx.ensure_object(dict)
    ctx.obj['config'] = config
    
    # Do not initialize handler yet, we only need it for subcommands
    # and they might have their own error handling.

async def get_handler(ctx: click.Context) -> APIServiceHandler:
    config = ctx.obj['config']
    handler = APIServiceHandler(config=config)
    try:
        await handler.initialize()
    except Exception as e:
        console.print(f"[bold red]Failed to initialize storage:[/bold red] {e}")
        ctx.exit(1)
    return handler

@cli.group()
def keys():
    """Manage API keys."""
    pass

@keys.command(name="add")
@click.option('--provider', required=True, help='API provider name (e.g. openai)')
@click.option('--key', required=True, help='The API key value')
@click.option('--alias', help='Optional human-friendly name')
@click.option('--daily-limit', type=int, help='Max requests per day')
@click.option('--monthly-limit', type=int, help='Max requests per month')
@click.option('--max-concurrent', type=int, help='Max simultaneous uses')
@click.option('--environment', default='production', help='Deployment environment')
@click.pass_context
@coro
async def keys_add(ctx: click.Context, provider: str, key: str, alias: Optional[str], 
                   daily_limit: Optional[int], monthly_limit: Optional[int], 
                   max_concurrent: Optional[int], environment: str):
    """Add a new API key."""
    handler = await get_handler(ctx)
    try:
        api_key = await handler.add_key(
            provider=provider,
            key_value=key,
            alias=alias,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
            max_concurrent=max_concurrent,
            environment=environment
        )
        console.print(f"[bold green]Successfully added key![/bold green]")
        console.print(f"ID: {api_key.id}")
        provider_str = api_key.provider if isinstance(api_key.provider, str) else api_key.provider.value
        console.print(f"Provider: {provider_str}")
        if alias:
            console.print(f"Alias: {api_key.alias}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@keys.command(name="list")
@click.option('--provider', help='Filter by provider')
@click.option('--status', help='Filter by status (e.g. active, revoked)')
@click.option('--show-keys', is_flag=True, help='Display full key values instead of masking')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
@click.pass_context
@coro
async def keys_list(ctx: click.Context, provider: Optional[str], status: Optional[str], 
                    show_keys: bool, as_json: bool):
    """List API keys."""
    handler = await get_handler(ctx)
    try:
        api_keys = await handler.get_all_keys(
            provider=provider, 
            status=status,
            decrypt=show_keys
        )
        
        if as_json:
            # Pydantic v2 compatible
            data = [k.model_dump(mode="json") for k in api_keys]
            console.print(json.dumps(data, indent=2))
            return

        table = Table(title="API Keys")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Provider", style="magenta")
        table.add_column("Alias")
        table.add_column("Key Value")
        table.add_column("Status")
        table.add_column("Usage (D/M/T)")

        for k in api_keys:
            key_val = k.key_value if show_keys else f"{k.key_value[:8]}***" if len(k.key_value) > 8 else "***"
            
            provider_str = k.provider if isinstance(k.provider, str) else k.provider.value
            status_str = k.status if isinstance(k.status, str) else k.status.value
            status_color = "green" if status_str == "active" else "red" if status_str == "revoked" else "yellow"
            status_text = f"[{status_color}]{status_str}[/{status_color}]"
            
            usage_text = f"{k.daily_usage_count}/{k.monthly_usage_count}/{k.total_usage_count}"
            
            table.add_row(
                k.id[:8] + "...", 
                provider_str, 
                k.alias or "-", 
                key_val, 
                status_text,
                usage_text
            )
            
        console.print(table)
        console.print(f"Total keys: {len(api_keys)}")
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@keys.command(name="get")
@click.argument('key_id')
@click.option('--show-key', is_flag=True, help='Display full key value instead of masking')
@click.pass_context
@coro
async def keys_get(ctx: click.Context, key_id: str, show_key: bool):
    """Get details for a specific API key."""
    handler = await get_handler(ctx)
    try:
        key = await handler.get_key(key_id, decrypt=show_key)
        
        console.print(f"[bold]Key Details for [cyan]{key.id}[/cyan][/bold]")
        provider_str = key.provider if isinstance(key.provider, str) else key.provider.value
        console.print(f"Provider:    {provider_str}")
        console.print(f"Alias:       {key.alias or '-'}")
        key_val = key.key_value if show_key else f"{key.key_value[:8]}***" if len(key.key_value) > 8 else "***"
        console.print(f"Key Value:   {key_val}")
        
        status_str = key.status if isinstance(key.status, str) else key.status.value
        status_color = "green" if status_str == "active" else "red" if status_str == "revoked" else "yellow"
        console.print(f"Status:      [{status_color}]{status_str}[/{status_color}]")
        
        env_str = key.environment if isinstance(key.environment, str) else key.environment.value
        console.print(f"Environment: {env_str}")
        
        console.print("\n[bold]Rate Limits & Usage[/bold]")
        console.print(f"Daily Limit:     {key.daily_limit or 'Unlimited'}")
        console.print(f"Daily Usage:     {key.daily_usage_count}")
        console.print(f"Monthly Limit:   {key.monthly_limit or 'Unlimited'}")
        console.print(f"Monthly Usage:   {key.monthly_usage_count}")
        console.print(f"Total Usage:     {key.total_usage_count}")
        console.print(f"Concurrent Max:  {key.max_concurrent or 'Unlimited'}")
        console.print(f"Concurrent Curr: {key.concurrent_usage}")
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@keys.command(name="update")
@click.argument('key_id')
@click.option('--alias', help='New human-friendly name')
@click.option('--status', help='New status (e.g. active, inactive)')
@click.option('--daily-limit', type=int, help='New max requests per day')
@click.option('--monthly-limit', type=int, help='New max requests per month')
@click.pass_context
@coro
async def keys_update(ctx: click.Context, key_id: str, alias: Optional[str], 
                      status: Optional[str], daily_limit: Optional[int], 
                      monthly_limit: Optional[int]):
    """Update an existing API key."""
    handler = await get_handler(ctx)
    try:
        updated = await handler.update_key(
            key_id,
            alias=alias,
            status=status,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit
        )
        console.print(f"[bold green]Successfully updated key {updated.id}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@keys.command(name="delete")
@click.argument('key_id')
@click.option('--hard', is_flag=True, help='Hard delete from database instead of revoking')
@click.pass_context
@coro
async def keys_delete(ctx: click.Context, key_id: str, hard: bool):
    """Delete or revoke an API key."""
    handler = await get_handler(ctx)
    try:
        if not click.confirm(f"Are you sure you want to {'hard ' if hard else 'soft '}delete key {key_id}?"):
            ctx.exit(0)
            
        await handler.delete_key(key_id, hard=hard)
        console.print(f"[bold green]Successfully deleted key {key_id}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@cli.group()
def usage():
    """View and reset usage statistics."""
    pass

@usage.command(name="stats")
@click.argument('key_id')
@click.pass_context
@coro
async def usage_stats(ctx: click.Context, key_id: str):
    """Get usage statistics for a specific key."""
    handler = await get_handler(ctx)
    try:
        stats = await handler.get_usage_stats(key_id)
        
        table = Table(title=f"Usage Stats for {key_id}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        
        provider_str = stats.provider if isinstance(stats.provider, str) else stats.provider.value
        table.add_row("Provider", provider_str)
        if stats.alias:
            table.add_row("Alias", stats.alias)
            
        table.add_row("Daily Usage", str(stats.daily_usage_count))
        table.add_row("Daily Remaining", str(stats.daily_remaining) if stats.daily_remaining is not None else "Unlimited")
        
        table.add_row("Monthly Usage", str(stats.monthly_usage_count))
        table.add_row("Monthly Remaining", str(stats.monthly_remaining) if stats.monthly_remaining is not None else "Unlimited")
        
        table.add_row("Total Usage", str(stats.total_usage_count))
        table.add_row("Concurrent", str(stats.concurrent_usage))
        
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@usage.command(name="reset-daily")
@click.pass_context
@coro
async def usage_reset_daily(ctx: click.Context):
    """Manually trigger daily reset for all keys."""
    handler = await get_handler(ctx)
    try:
        count = await handler.reset_daily_counts()
        console.print(f"[bold green]Reset daily counters for {count} keys.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@usage.command(name="reset-monthly")
@click.pass_context
@coro
async def usage_reset_monthly(ctx: click.Context):
    """Manually trigger monthly reset for all keys."""
    handler = await get_handler(ctx)
    try:
        count = await handler.reset_monthly_counts()
        console.print(f"[bold green]Reset monthly counters for {count} keys.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@cli.command()
@click.pass_context
@coro
async def health(ctx: click.Context):
    """Check the health of the storage backend."""
    handler = await get_handler(ctx)
    try:
        status = await handler.health_check()
        if status.get("storage_healthy"):
            console.print("[bold green]Storage backend is healthy![/bold green]")
        else:
            console.print("[bold red]Storage backend is NOT healthy![/bold red]")
            
        for k, v in status.items():
            console.print(f"{k}: {v}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

@cli.command()
@click.pass_context
@coro
async def info(ctx: click.Context):
    """View API Service Handler information and stats."""
    handler = await get_handler(ctx)
    try:
        inf = await handler.info()
        console.print("[bold]API Service Handler Info[/bold]")
        for k, v in inf.items():
            console.print(f"{k}: {v}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
    finally:
        await handler.close()

if __name__ == '__main__':
    cli()
