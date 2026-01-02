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


def get_batch_derivation_metadata(drv_paths: list[str], timeout_per_batch: int = 60) -> dict[str, dict]:
    """Get metadata for multiple derivations in a single call.

    nix derivation show can accept multiple paths, which is more efficient.

    Args:
        drv_paths: List of derivation paths
        timeout_per_batch: Timeout in seconds for the batch

    Returns:
        Dict mapping drv_path to its metadata
    """
    if not drv_paths:
        return {}

    cmd = ["nix", "derivation", "show"] + drv_paths

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_per_batch,
        )

        if result.returncode != 0:
            # Fall back to individual fetches for failed batch
            return {}

        import json
        data = json.loads(result.stdout)
        return data
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    except FileNotFoundError:
        return {}


def get_top_level_packages_extended(host: str, config_path: Path | None = None) -> dict[str, str]:
    """Get top-level packages with their source.

    Returns a dictionary mapping package names to their source (e.g., 'systemPackages').
    This is used to mark nodes as "user-facing" vs transitive dependencies.

    Supports:
    - environment.systemPackages
    - programs.*.enable (e.g., programs.git.enable adds git)
    - services.*.enable (e.g., services.nginx.enable adds nginx)

    Args:
        host: The NixOS host name
        config_path: Optional path to the nix config (defaults to settings.nix_config_path)

    Returns:
        Dictionary mapping package name to source string
    """
    result: dict[str, str] = {}

    # Get environment.systemPackages
    system_pkgs = get_system_packages(host, config_path)
    for pkg in system_pkgs:
        result[pkg] = 'systemPackages'

    # Get enabled programs (programs.*.enable)
    enabled_programs = get_enabled_programs(host, config_path)
    for prog_name in enabled_programs:
        # Program name usually maps directly to package name
        result[prog_name] = f'programs.{prog_name}.enable'

    # Get enabled services (services.*.enable)
    enabled_services = get_enabled_services(host, config_path)
    for svc_name in enabled_services:
        # Map service name to likely package name(s)
        pkg_names = map_service_to_packages(svc_name)
        for pkg_name in pkg_names:
            result[pkg_name] = f'services.{svc_name}.enable'

    return result


# =============================================================================
# Module Attribution - Enabled Programs Detection
# =============================================================================


def get_enabled_programs(host: str, config_path: Path | None = None) -> list[str]:
    """Get list of programs enabled via programs.*.enable options.

    Evaluates the NixOS configuration to find which programs.* modules
    are enabled (have enable = true).

    Args:
        host: The NixOS host name
        config_path: Optional path to the nix config

    Returns:
        List of program names that are enabled (e.g., ['git', 'vim', 'zsh'])
    """
    config_path = config_path or settings.nix_config_path

    # Evaluate which programs are enabled
    # The Nix expression gets all programs.*.enable options that are true
    cmd = [
        "nix", "eval",
        f".#nixosConfigurations.{host}.config.programs",
        "--apply", """
            programs:
            builtins.filter (name: name != null) (
                builtins.attrValues (
                    builtins.mapAttrs (name: cfg:
                        if builtins.isAttrs cfg && cfg ? enable && cfg.enable == true
                        then name
                        else null
                    ) programs
                )
            )
        """,
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
            # Fallback: try simpler evaluation approach
            return _get_enabled_programs_fallback(host, config_path)

        import json
        programs = json.loads(result.stdout)
        return sorted(set(programs)) if isinstance(programs, list) else []

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def _get_enabled_programs_fallback(host: str, config_path: Path) -> list[str]:
    """Fallback method to detect enabled programs using simpler evaluation.

    Uses pattern-based detection for common programs that are typically enabled.
    """
    # List of common programs to check
    common_programs = [
        "git", "vim", "neovim", "zsh", "bash", "fish",
        "gnupg", "ssh", "tmux", "htop", "starship",
        "direnv", "fzf", "bat", "ripgrep", "fd", "jq",
        "chromium", "firefox", "thunderbird",
    ]

    enabled = []
    for prog in common_programs:
        cmd = [
            "nix", "eval",
            f".#nixosConfigurations.{host}.config.programs.{prog}.enable",
            "--json",
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(config_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip() == "true":
                enabled.append(prog)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return enabled


# =============================================================================
# Module Attribution - Enabled Services Detection
# =============================================================================


def get_enabled_services(host: str, config_path: Path | None = None) -> list[str]:
    """Get list of services enabled via services.*.enable options.

    Evaluates the NixOS configuration to find which services.* modules
    are enabled (have enable = true).

    Args:
        host: The NixOS host name
        config_path: Optional path to the nix config

    Returns:
        List of service names that are enabled (e.g., ['nginx', 'postgresql', 'sshd'])
    """
    config_path = config_path or settings.nix_config_path

    # Evaluate which services are enabled
    # The Nix expression gets all services.*.enable options that are true
    cmd = [
        "nix", "eval",
        f".#nixosConfigurations.{host}.config.services",
        "--apply", """
            services:
            builtins.filter (name: name != null) (
                builtins.attrValues (
                    builtins.mapAttrs (name: cfg:
                        if builtins.isAttrs cfg && cfg ? enable && cfg.enable == true
                        then name
                        else null
                    ) services
                )
            )
        """,
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
            # Fallback: try simpler evaluation approach
            return _get_enabled_services_fallback(host, config_path)

        import json
        services = json.loads(result.stdout)
        return sorted(set(services)) if isinstance(services, list) else []

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def _get_enabled_services_fallback(host: str, config_path: Path) -> list[str]:
    """Fallback method to detect enabled services using simpler evaluation.

    Uses pattern-based detection for common services that are typically enabled.
    """
    # List of common services to check
    common_services = [
        "nginx", "postgresql", "mysql", "redis", "openssh", "sshd",
        "docker", "podman", "libvirtd", "xserver", "displayManager",
        "pipewire", "pulseaudio", "printing", "avahi", "dbus",
        "networkmanager", "resolved", "tailscale", "syncthing",
        "home-assistant", "grafana", "prometheus", "loki",
    ]

    enabled = []
    for svc in common_services:
        cmd = [
            "nix", "eval",
            f".#nixosConfigurations.{host}.config.services.{svc}.enable",
            "--json",
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(config_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip() == "true":
                enabled.append(svc)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return enabled


# =============================================================================
# Module Attribution - Service to Package Mapping
# =============================================================================


# Mapping from service names to their primary package names
# Some services use different package names than their module names
SERVICE_TO_PACKAGE_MAP = {
    # Web servers
    "nginx": ["nginx"],
    "apache": ["apacheHttpd"],
    "caddy": ["caddy"],
    "lighttpd": ["lighttpd"],

    # Databases
    "postgresql": ["postgresql"],
    "mysql": ["mysql", "mariadb"],
    "redis": ["redis"],
    "mongodb": ["mongodb"],
    "elasticsearch": ["elasticsearch"],

    # SSH
    "openssh": ["openssh"],
    "sshd": ["openssh"],

    # Container/virtualization
    "docker": ["docker"],
    "podman": ["podman"],
    "libvirtd": ["libvirt", "qemu"],
    "virtualbox": ["virtualbox"],

    # Desktop
    "xserver": ["xorg-server", "xwayland"],
    "displayManager": [],  # Depends on which DM is configured
    "pipewire": ["pipewire"],
    "pulseaudio": ["pulseaudio"],

    # Networking
    "networkmanager": ["networkmanager"],
    "tailscale": ["tailscale"],
    "wireguard": ["wireguard-tools"],
    "openvpn": ["openvpn"],

    # System services
    "dbus": ["dbus"],
    "avahi": ["avahi"],
    "printing": ["cups"],
    "resolved": ["systemd"],  # Part of systemd

    # Monitoring
    "prometheus": ["prometheus"],
    "grafana": ["grafana"],
    "loki": ["loki"],

    # Home automation
    "home-assistant": ["home-assistant"],

    # Sync
    "syncthing": ["syncthing"],
    "nextcloud": ["nextcloud"],

    # Media
    "jellyfin": ["jellyfin"],
    "plex": ["plex"],

    # Email
    "postfix": ["postfix"],
    "dovecot": ["dovecot"],
}


def map_service_to_packages(service_name: str) -> list[str]:
    """Map a service name to its associated package names.

    Many NixOS services use different package names than their module names.
    This function provides a mapping from service name to likely package names.

    Args:
        service_name: The service name (e.g., 'nginx', 'postgresql')

    Returns:
        List of package names associated with this service
    """
    # Check explicit mapping first
    if service_name in SERVICE_TO_PACKAGE_MAP:
        return SERVICE_TO_PACKAGE_MAP[service_name]

    # Default: assume service name matches package name
    # This works for many services (e.g., nginx, redis, etc.)
    return [service_name]


def get_module_attribution(host: str, config_path: Path | None = None) -> dict[str, list[str]]:
    """Get comprehensive module attribution for a host configuration.

    Returns a mapping of package names to the list of modules that add them.
    A package may be added by multiple modules (e.g., openssl might be pulled
    by both systemPackages and services.nginx).

    Args:
        host: The NixOS host name
        config_path: Optional path to the nix config

    Returns:
        Dictionary mapping package name to list of module sources
    """
    result: dict[str, list[str]] = {}

    # Get all sources
    top_level = get_top_level_packages_extended(host, config_path)

    for pkg_name, source in top_level.items():
        if pkg_name not in result:
            result[pkg_name] = []
        result[pkg_name].append(source)

    return result


def extract_metadata_summary(full_metadata: dict) -> dict:
    """Extract a summary of useful metadata from nix derivation show output.

    This creates a smaller, more useful subset for display.
    """
    if not full_metadata:
        return {}

    summary = {}

    # System architecture
    if "system" in full_metadata:
        summary["system"] = full_metadata["system"]

    # Builder
    if "builder" in full_metadata:
        summary["builder"] = full_metadata["builder"]

    # Output paths
    if "outputs" in full_metadata:
        summary["outputs"] = {
            name: info.get("path", "")
            for name, info in full_metadata.get("outputs", {}).items()
        }

    # Input derivations (dependencies) - just count them
    if "inputDrvs" in full_metadata:
        summary["input_drv_count"] = len(full_metadata["inputDrvs"])

    # Input sources
    if "inputSrcs" in full_metadata:
        summary["input_src_count"] = len(full_metadata["inputSrcs"])

    # Environment variables - extract key ones
    env = full_metadata.get("env", {})
    if env:
        interesting_keys = ["name", "pname", "version", "src", "buildInputs", "nativeBuildInputs"]
        summary["env"] = {k: env[k] for k in interesting_keys if k in env}

        # Also extract any URL-like values (sources)
        if "src" in env and isinstance(env["src"], str):
            summary["source"] = env["src"]

    return summary
