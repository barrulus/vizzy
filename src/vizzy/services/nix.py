"""Nix CLI integration service"""

import subprocess
import tempfile
from pathlib import Path

from vizzy.config import settings


class NixError(Exception):
    """Error running nix command"""
    pass


def get_drv_path(host: str, config_path: Path | None = None) -> str:
    """Get the derivation path for a NixOS host configuration.

    Runs: nix eval .#nixosConfigurations.{host}.config.system.build.toplevel.drvPath --raw
    """
    config_path = config_path or settings.nix_config_path

    cmd = [
        "nix", "eval",
        f".#nixosConfigurations.{host}.config.system.build.toplevel.drvPath",
        "--raw",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(config_path),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes - evaluation can be slow
        )

        if result.returncode != 0:
            raise NixError(f"nix eval failed: {result.stderr}")

        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise NixError("nix eval timed out (>5 minutes)")
    except FileNotFoundError:
        raise NixError("nix command not found")


def generate_graph(drv_path: str) -> str:
    """Generate DOT graph for a derivation.

    Runs: nix-store -q --graph {drv_path}
    """
    cmd = ["nix-store", "-q", "--graph", drv_path]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise NixError(f"nix-store --graph failed: {result.stderr}")

        return result.stdout
    except subprocess.TimeoutExpired:
        raise NixError("nix-store --graph timed out (>2 minutes)")
    except FileNotFoundError:
        raise NixError("nix-store command not found")


def export_host_graph(host: str, config_path: Path | None = None) -> tuple[str, Path]:
    """Export a NixOS host's dependency graph to a temporary DOT file.

    Returns (drv_path, dot_file_path)
    """
    config_path = config_path or settings.nix_config_path

    # Get derivation path
    drv_path = get_drv_path(host, config_path)

    # Generate graph DOT content
    dot_content = generate_graph(drv_path)

    # Write to temp file
    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".dot",
        prefix=f"vizzy-{host}-",
        delete=False,
    )
    temp_file.write(dot_content)
    temp_file.close()

    return drv_path, Path(temp_file.name)


def get_system_packages(host: str, config_path: Path | None = None) -> list[str]:
    """Get the list of explicitly defined system packages for a host.

    Returns package names from config.environment.systemPackages.
    """
    config_path = config_path or settings.nix_config_path

    cmd = [
        "nix", "eval",
        f".#nixosConfigurations.{host}.config.environment.systemPackages",
        "--apply", "pkgs: map (p: p.name or p.pname or (builtins.parseDrvName p.name).name or \"unknown\") pkgs",
        "--json",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(config_path),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            # Try alternative approach - just get names
            cmd_alt = [
                "nix", "eval",
                f".#nixosConfigurations.{host}.config.environment.systemPackages",
                "--apply", "pkgs: map (p: p.name or \"unknown\") pkgs",
                "--json",
            ]
            result = subprocess.run(
                cmd_alt,
                cwd=str(config_path),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return []

        import json
        packages = json.loads(result.stdout)
        # Remove duplicates and sort
        return sorted(set(packages))

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def get_derivation_metadata(drv_path: str) -> dict:
    """Get detailed metadata for a derivation.

    Runs: nix derivation show {drv_path}
    """
    cmd = ["nix", "derivation", "show", drv_path]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return {}

        import json
        data = json.loads(result.stdout)
        # Returns dict with drv_path as key
        return data.get(drv_path, {})
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    except FileNotFoundError:
        return {}
