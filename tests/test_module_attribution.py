"""Tests for enhanced module attribution functionality (Phase 8A-005)

These tests verify the module attribution system that tracks which NixOS
modules (systemPackages, programs.*, services.*) are responsible for
adding packages to the system configuration.
"""

import pytest
from unittest.mock import patch, MagicMock

from vizzy.services.importer import _classify_module_type, mark_top_level_nodes
from vizzy.services.nix import (
    get_enabled_programs,
    get_enabled_services,
    get_top_level_packages_extended,
    map_service_to_packages,
    get_module_attribution,
    SERVICE_TO_PACKAGE_MAP,
)
from vizzy.models import Node


class TestModuleTypeClassification:
    """Test the _classify_module_type helper function"""

    def test_system_packages_classification(self):
        """systemPackages should be classified as 'systemPackages'"""
        result = _classify_module_type('systemPackages')
        assert result == 'systemPackages'

    def test_programs_classification(self):
        """programs.* sources should be classified as 'programs'"""
        result = _classify_module_type('programs.git.enable')
        assert result == 'programs'

        result = _classify_module_type('programs.neovim.enable')
        assert result == 'programs'

    def test_services_classification(self):
        """services.* sources should be classified as 'services'"""
        result = _classify_module_type('services.nginx.enable')
        assert result == 'services'

        result = _classify_module_type('services.postgresql.enable')
        assert result == 'services'

    def test_other_classification(self):
        """Unknown sources should be classified as 'other'"""
        result = _classify_module_type('home-manager.packages')
        assert result == 'other'

        result = _classify_module_type('custom.module')
        assert result == 'other'


class TestServiceToPackageMapping:
    """Test the service-to-package mapping functionality"""

    def test_nginx_mapping(self):
        """nginx service should map to nginx package"""
        result = map_service_to_packages('nginx')
        assert result == ['nginx']

    def test_postgresql_mapping(self):
        """postgresql service should map to postgresql package"""
        result = map_service_to_packages('postgresql')
        assert result == ['postgresql']

    def test_mysql_mapping(self):
        """mysql service should map to both mysql and mariadb"""
        result = map_service_to_packages('mysql')
        assert 'mysql' in result
        assert 'mariadb' in result

    def test_openssh_mapping(self):
        """openssh service should map to openssh package"""
        result = map_service_to_packages('openssh')
        assert result == ['openssh']

    def test_sshd_maps_to_openssh(self):
        """sshd service should also map to openssh package"""
        result = map_service_to_packages('sshd')
        assert result == ['openssh']

    def test_libvirtd_mapping(self):
        """libvirtd service should map to libvirt and qemu"""
        result = map_service_to_packages('libvirtd')
        assert 'libvirt' in result
        assert 'qemu' in result

    def test_unknown_service_fallback(self):
        """Unknown service should fallback to service name as package"""
        result = map_service_to_packages('unknown-service')
        assert result == ['unknown-service']

    def test_printing_maps_to_cups(self):
        """printing service should map to cups package"""
        result = map_service_to_packages('printing')
        assert result == ['cups']


class TestGetEnabledPrograms:
    """Test the get_enabled_programs function"""

    def test_parses_enabled_programs_list(self):
        """Should parse list of enabled programs from nix output"""
        with patch('vizzy.services.nix.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '["git", "vim", "zsh"]'
            mock_run.return_value = mock_result

            result = get_enabled_programs('testhost')

            assert result == ['git', 'vim', 'zsh']

    def test_handles_empty_programs_list(self):
        """Should handle empty programs list"""
        with patch('vizzy.services.nix.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '[]'
            mock_run.return_value = mock_result

            result = get_enabled_programs('testhost')

            assert result == []

    def test_fallback_on_failed_eval(self):
        """Should use fallback when primary evaluation fails"""
        with patch('vizzy.services.nix.subprocess.run') as mock_run:
            # First call fails, fallback calls also fail
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "evaluation error"
            mock_run.return_value = mock_result

            result = get_enabled_programs('testhost')

            # Should return empty when all calls fail
            assert result == []


class TestGetEnabledServices:
    """Test the get_enabled_services function"""

    def test_parses_enabled_services_list(self):
        """Should parse list of enabled services from nix output"""
        with patch('vizzy.services.nix.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '["nginx", "postgresql", "openssh"]'
            mock_run.return_value = mock_result

            result = get_enabled_services('testhost')

            assert result == ['nginx', 'openssh', 'postgresql']  # Sorted

    def test_deduplicates_services(self):
        """Should remove duplicate service names"""
        with patch('vizzy.services.nix.subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '["nginx", "nginx", "redis"]'
            mock_run.return_value = mock_result

            result = get_enabled_services('testhost')

            assert result == ['nginx', 'redis']


class TestGetTopLevelPackagesExtended:
    """Test the enhanced get_top_level_packages_extended function"""

    def test_includes_system_packages(self):
        """Should include packages from environment.systemPackages"""
        with patch('vizzy.services.nix.get_system_packages') as mock_sys:
            with patch('vizzy.services.nix.get_enabled_programs') as mock_progs:
                with patch('vizzy.services.nix.get_enabled_services') as mock_svcs:
                    mock_sys.return_value = ['firefox', 'git']
                    mock_progs.return_value = []
                    mock_svcs.return_value = []

                    result = get_top_level_packages_extended('testhost')

                    assert result['firefox'] == 'systemPackages'
                    assert result['git'] == 'systemPackages'

    def test_includes_enabled_programs(self):
        """Should include packages from programs.*.enable"""
        with patch('vizzy.services.nix.get_system_packages') as mock_sys:
            with patch('vizzy.services.nix.get_enabled_programs') as mock_progs:
                with patch('vizzy.services.nix.get_enabled_services') as mock_svcs:
                    mock_sys.return_value = []
                    mock_progs.return_value = ['git', 'vim']
                    mock_svcs.return_value = []

                    result = get_top_level_packages_extended('testhost')

                    assert result['git'] == 'programs.git.enable'
                    assert result['vim'] == 'programs.vim.enable'

    def test_includes_enabled_services(self):
        """Should include packages from services.*.enable"""
        with patch('vizzy.services.nix.get_system_packages') as mock_sys:
            with patch('vizzy.services.nix.get_enabled_programs') as mock_progs:
                with patch('vizzy.services.nix.get_enabled_services') as mock_svcs:
                    mock_sys.return_value = []
                    mock_progs.return_value = []
                    mock_svcs.return_value = ['nginx', 'postgresql']

                    result = get_top_level_packages_extended('testhost')

                    assert result['nginx'] == 'services.nginx.enable'
                    assert result['postgresql'] == 'services.postgresql.enable'

    def test_service_package_mapping_applied(self):
        """Should apply service-to-package mapping for known services"""
        with patch('vizzy.services.nix.get_system_packages') as mock_sys:
            with patch('vizzy.services.nix.get_enabled_programs') as mock_progs:
                with patch('vizzy.services.nix.get_enabled_services') as mock_svcs:
                    mock_sys.return_value = []
                    mock_progs.return_value = []
                    mock_svcs.return_value = ['printing']  # Maps to cups

                    result = get_top_level_packages_extended('testhost')

                    assert result['cups'] == 'services.printing.enable'

    def test_combined_sources(self):
        """Should combine all sources correctly"""
        with patch('vizzy.services.nix.get_system_packages') as mock_sys:
            with patch('vizzy.services.nix.get_enabled_programs') as mock_progs:
                with patch('vizzy.services.nix.get_enabled_services') as mock_svcs:
                    mock_sys.return_value = ['firefox']
                    mock_progs.return_value = ['git']
                    mock_svcs.return_value = ['nginx']

                    result = get_top_level_packages_extended('testhost')

                    assert len(result) == 3
                    assert result['firefox'] == 'systemPackages'
                    assert result['git'] == 'programs.git.enable'
                    assert result['nginx'] == 'services.nginx.enable'


class TestGetModuleAttribution:
    """Test the get_module_attribution function"""

    def test_returns_packages_with_sources(self):
        """Should return packages mapped to their source modules"""
        with patch('vizzy.services.nix.get_top_level_packages_extended') as mock_extended:
            mock_extended.return_value = {
                'firefox': 'systemPackages',
                'git': 'programs.git.enable',
                'nginx': 'services.nginx.enable',
            }

            result = get_module_attribution('testhost')

            assert 'firefox' in result
            assert 'systemPackages' in result['firefox']
            assert 'git' in result
            assert 'programs.git.enable' in result['git']


class TestNodeModelWithModuleType:
    """Test the Node model includes module_type field"""

    def test_node_has_module_type_field(self):
        """Node should have module_type field"""
        node = Node(
            id=1,
            import_id=1,
            drv_hash="abc123",
            drv_name="nginx-1.25.0.drv",
            label="nginx-1.25.0",
            package_type="service",
            depth=1,
            closure_size=100,
            metadata=None,
            is_top_level=True,
            top_level_source="services.nginx.enable",
            module_type="services",
        )

        assert node.module_type == "services"

    def test_node_module_type_defaults_to_none(self):
        """Node module_type should default to None"""
        node = Node(
            id=1,
            import_id=1,
            drv_hash="abc123",
            drv_name="test-1.0.drv",
            label="test-1.0",
            package_type="app",
            depth=1,
            closure_size=10,
            metadata=None,
        )

        assert node.module_type is None


class TestMarkTopLevelNodesWithModuleType:
    """Test that mark_top_level_nodes sets module_type correctly"""

    def test_marks_nodes_with_module_type(self):
        """Should mark nodes with both source and module_type"""
        with patch('vizzy.services.importer.nix') as mock_nix:
            with patch('vizzy.services.importer.get_db') as mock_get_db:
                mock_nix.get_top_level_packages_extended.return_value = {
                    'firefox': 'systemPackages',
                    'git': 'programs.git.enable',
                    'nginx': 'services.nginx.enable',
                }

                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_get_db.return_value.__enter__.return_value = mock_conn
                mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
                mock_cursor.rowcount = 1

                result = mark_top_level_nodes(import_id=1, host="testhost")

                assert result == 3  # 3 packages marked

                # Verify UPDATE includes module_type
                calls = mock_cursor.execute.call_args_list
                for call in calls:
                    sql = call[0][0]
                    params = call[0][1]
                    assert 'module_type' in sql
                    # Check that module_type is passed as parameter
                    assert params[1] in ['systemPackages', 'programs', 'services', 'other']


class TestServiceToPackageMapCompleteness:
    """Verify the SERVICE_TO_PACKAGE_MAP covers common services"""

    def test_web_servers_mapped(self):
        """Common web servers should be mapped"""
        assert 'nginx' in SERVICE_TO_PACKAGE_MAP
        assert 'apache' in SERVICE_TO_PACKAGE_MAP
        assert 'caddy' in SERVICE_TO_PACKAGE_MAP

    def test_databases_mapped(self):
        """Common databases should be mapped"""
        assert 'postgresql' in SERVICE_TO_PACKAGE_MAP
        assert 'mysql' in SERVICE_TO_PACKAGE_MAP
        assert 'redis' in SERVICE_TO_PACKAGE_MAP

    def test_container_services_mapped(self):
        """Container/virtualization services should be mapped"""
        assert 'docker' in SERVICE_TO_PACKAGE_MAP
        assert 'podman' in SERVICE_TO_PACKAGE_MAP
        assert 'libvirtd' in SERVICE_TO_PACKAGE_MAP

    def test_monitoring_services_mapped(self):
        """Monitoring services should be mapped"""
        assert 'prometheus' in SERVICE_TO_PACKAGE_MAP
        assert 'grafana' in SERVICE_TO_PACKAGE_MAP
