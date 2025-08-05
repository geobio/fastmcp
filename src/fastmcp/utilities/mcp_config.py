import asyncio
from typing import Any

from fastmcp.mcp_config import MCPConfig
from fastmcp.server.server import FastMCP


def composite_server_from_mcp_config(
    config: MCPConfig, name_as_prefix: bool = True
):
    """A utility function to create a composite server from an MCPConfig."""
    composite_server = FastMCP()

    mount_mcp_config_into_server(config, composite_server, name_as_prefix)

    return composite_server


async def composite_server_from_mcp_config_async(
    config: MCPConfig, 
    name_as_prefix: bool = True,
    max_concurrent: int = 10,
    fail_fast: bool = False
):
    """An async utility function to create a composite server from an MCPConfig with parallel mounting.
    
    Args:
        config: MCPConfig with server definitions
        name_as_prefix: Whether to use server names as prefixes
        max_concurrent: Maximum number of servers to mount concurrently (default: 10)
        fail_fast: If True, fail immediately on first error. If False, continue with working servers.
    """
    composite_server = FastMCP()

    await mount_mcp_config_into_server_async(
        config, composite_server, name_as_prefix, max_concurrent, fail_fast
    )

    return composite_server


def mount_mcp_config_into_server(
    config: MCPConfig,
    server,
    name_as_prefix: bool = True,
) -> None:
    """A utility function to mount the servers from an MCPConfig into a FastMCP server."""
    for name, mcp_server in config.mcpServers.items():
        server.mount(
            prefix=name if name_as_prefix else None,
            server=FastMCP.as_proxy(backend=mcp_server.to_transport()),
        )


async def mount_mcp_config_into_server_async(
    config: MCPConfig,
    server,
    name_as_prefix: bool = True,
    max_concurrent: int = 10,
    fail_fast: bool = False
) -> None:
    """An async utility function to mount servers with controlled concurrency and error handling.
    
    Args:
        config: MCPConfig with server definitions
        server: FastMCP server to mount into
        name_as_prefix: Whether to use server names as prefixes
        max_concurrent: Maximum concurrent server mounts (prevents resource exhaustion)
        fail_fast: If True, stop on first error. If False, collect errors and continue.
    """
    
    async def mount_single_server(name: str, mcp_server: Any) -> tuple[str, bool, Exception | None]:
        """Mount a single server as a proxy with error handling."""
        import io
        import sys
        from contextlib import redirect_stdout, redirect_stderr
        
        # Capture all output from this server
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        
        try:
            # Redirect stdout and stderr to buffers to capture subprocess output
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                proxy_server = FastMCP.as_proxy(backend=mcp_server.to_transport())
                server.mount(
                    prefix=name if name_as_prefix else None,
                    server=proxy_server,
                )
            
            # Get captured output
            stdout_content = stdout_buffer.getvalue().strip()
            stderr_content = stderr_buffer.getvalue().strip()
            
            # Print grouped output for this server
            print(f"\n{'='*60}")
            print(f"✅ {name} - MOUNTED SUCCESSFULLY")
            print(f"{'='*60}")
            if stdout_content:
                print("📤 Output:")
                print(stdout_content)
            if stderr_content:
                print("⚠️ Warnings:")
                print(stderr_content)
            print(f"{'='*60}\n")
            
            return name, True, None
            
        except Exception as e:
            # Get captured output even on failure
            stdout_content = stdout_buffer.getvalue().strip()
            stderr_content = stderr_buffer.getvalue().strip()
            
            # Print grouped output for failed server
            print(f"\n{'='*60}")
            print(f"❌ {name} - FAILED: {e}")
            print(f"{'='*60}")
            if stdout_content:
                print("📤 Output:")
                print(stdout_content)
            if stderr_content:
                print("🚨 Errors:")
                print(stderr_content)
            print(f"{'='*60}\n")
            
            return name, False, e

    # Use semaphore to limit concurrent operations
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def bounded_mount(name: str, mcp_server: Any):
        async with semaphore:
            return await mount_single_server(name, mcp_server)

    # Create all mounting tasks with concurrency control
    tasks = [
        bounded_mount(name, mcp_server)
        for name, mcp_server in config.mcpServers.items()
    ]

    # Execute with appropriate error handling
    if fail_fast:
        # Original behavior - fail on first error
        await asyncio.gather(*tasks)
    else:
        # Graceful degradation - collect errors but continue
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_mounts = []
        failed_mounts = []
        
        for result in results:
            if isinstance(result, Exception):
                failed_mounts.append(f"Unknown server: {result}")
            else:
                name, success, error = result
                if success:
                    successful_mounts.append(name)
                else:
                    failed_mounts.append(f"{name}: {error}")
        
        # Log results
        if successful_mounts:
            print(f"✅ Successfully mounted {len(successful_mounts)} servers: {', '.join(successful_mounts)}")
        
        if failed_mounts:
            print(f"❌ Failed to mount {len(failed_mounts)} servers:")
            for failure in failed_mounts:
                print(f"   - {failure}")
            
            # Still raise if ALL servers failed
            if not successful_mounts:
                raise RuntimeError(f"All {len(failed_mounts)} servers failed to mount")
