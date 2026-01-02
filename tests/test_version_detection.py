"""Tests for version difference detection functionality (Task 8F-002)"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from vizzy.models import (
    DiffType,
    ImportInfo,
    Node,
    NodeDiff,
    ImportComparison,
    VersionChangeType,
    VersionDiff,
    VersionComparisonResult,
)
from vizzy.services.comparison import (
    extract_version,
    parse_version_components,
    compare_versions,
    classify_version_change,
    detect_version_changes,
    generate_version_summary,
)


class TestExtractVersion:
    """Test the extract_version function"""

    def test_standard_semver(self):
        """Standard semantic version: name-1.2.3"""
        name, version = extract_version("openssl-3.0.12")
        assert name == "openssl"
        assert version == "3.0.12"

    def test_version_with_patch_number(self):
        """Version with patch number: name-1.2.3-4"""
        name, version = extract_version("glibc-2.40-66")
        assert name == "glibc"
        assert version == "2.40-66"

    def test_name_with_version_number(self):
        """Package name contains version number: python3-3.11.7"""
        name, version = extract_version("python3-3.11.7")
        assert name == "python3"
        assert version == "3.11.7"

    def test_no_version(self):
        """Package without version number"""
        name, version = extract_version("bootstrap-tools")
        assert name == "bootstrap-tools"
        assert version is None

    def test_wrapper_package(self):
        """Package with wrapper suffix: gcc-wrapper-13.2.0"""
        name, version = extract_version("gcc-wrapper-13.2.0")
        assert name == "gcc-wrapper"
        assert version == "13.2.0"

    def test_simple_version(self):
        """Simple package version: nix-2.18.1"""
        name, version = extract_version("nix-2.18.1")
        assert name == "nix"
        assert version == "2.18.1"

    def test_kernel_version(self):
        """Linux kernel version: linux-6.6.8"""
        name, version = extract_version("linux-6.6.8")
        assert name == "linux"
        assert version == "6.6.8"

    def test_app_version(self):
        """Application version: firefox-120.0.1"""
        name, version = extract_version("firefox-120.0.1")
        assert name == "firefox"
        assert version == "120.0.1"

    def test_perl_module(self):
        """Perl module with interpreter version: perl5.38.2-URI-5.21"""
        name, version = extract_version("perl5.38.2-URI-5.21")
        assert name == "perl5.38.2-URI"
        assert version == "5.21"

    def test_date_version(self):
        """Date-based version: package-20231215"""
        name, version = extract_version("package-20231215")
        assert name == "package"
        assert version == "20231215"

    def test_unstable_version(self):
        """Unstable/git version: package-unstable-2023-12-15"""
        name, version = extract_version("package-unstable-2023-12-15")
        assert name == "package"
        assert version == "unstable-2023-12-15"

    def test_single_digit_version(self):
        """Single digit version: package-5"""
        name, version = extract_version("package-5")
        assert name == "package"
        assert version == "5"

    def test_empty_string(self):
        """Empty string should return empty name and no version"""
        name, version = extract_version("")
        assert name == ""
        assert version is None


class TestParseVersionComponents:
    """Test the parse_version_components function"""

    def test_simple_semver(self):
        """Simple semantic version: 3.0.12"""
        components = parse_version_components("3.0.12")
        assert components == [3, 0, 12]

    def test_version_with_dash(self):
        """Version with dash separator: 2.40-66"""
        components = parse_version_components("2.40-66")
        assert components == [2, 40, 66]

    def test_version_with_alpha(self):
        """Version with alpha component: 1.0rc1"""
        components = parse_version_components("1.0rc1")
        assert components == [1, 0, "rc", 1]

    def test_version_with_beta(self):
        """Version with beta component: 2.0.0beta3"""
        components = parse_version_components("2.0.0beta3")
        assert components == [2, 0, 0, "beta", 3]

    def test_version_with_underscore(self):
        """Version with underscore: 1.0_pre1"""
        components = parse_version_components("1.0_pre1")
        assert components == [1, 0, "pre", 1]

    def test_date_version(self):
        """Date-based version: 20231215"""
        components = parse_version_components("20231215")
        assert components == [20231215]

    def test_complex_version(self):
        """Complex version: 5.4.3-2.1"""
        components = parse_version_components("5.4.3-2.1")
        assert components == [5, 4, 3, 2, 1]


class TestCompareVersions:
    """Test the compare_versions function"""

    def test_equal_versions(self):
        """Equal versions should return 0"""
        assert compare_versions("1.0", "1.0") == 0
        assert compare_versions("3.0.12", "3.0.12") == 0

    def test_upgrade_major(self):
        """Major version upgrade: 1.0 -> 2.0 returns -1"""
        assert compare_versions("1.0", "2.0") == -1

    def test_upgrade_minor(self):
        """Minor version upgrade: 1.0 -> 1.1 returns -1"""
        assert compare_versions("1.0", "1.1") == -1

    def test_upgrade_patch(self):
        """Patch version upgrade: 1.0.0 -> 1.0.1 returns -1"""
        assert compare_versions("1.0.0", "1.0.1") == -1

    def test_downgrade_major(self):
        """Major version downgrade: 2.0 -> 1.0 returns 1"""
        assert compare_versions("2.0", "1.0") == 1

    def test_downgrade_minor(self):
        """Minor version downgrade: 1.1 -> 1.0 returns 1"""
        assert compare_versions("1.1", "1.0") == 1

    def test_downgrade_patch(self):
        """Patch version downgrade: 1.0.1 -> 1.0.0 returns 1"""
        assert compare_versions("1.0.1", "1.0.0") == 1

    def test_none_left(self):
        """None left version returns 0 (can't compare)"""
        assert compare_versions(None, "1.0") == 0

    def test_none_right(self):
        """None right version returns 0 (can't compare)"""
        assert compare_versions("1.0", None) == 0

    def test_both_none(self):
        """Both None returns 0"""
        assert compare_versions(None, None) == 0

    def test_different_length(self):
        """Different length versions: 1.0 < 1.0.1"""
        assert compare_versions("1.0", "1.0.1") == -1
        assert compare_versions("1.0.1", "1.0") == 1

    def test_prerelease_comparison(self):
        """Pre-release versions should compare correctly"""
        # alpha < beta < rc < release
        assert compare_versions("1.0alpha1", "1.0beta1") == -1
        assert compare_versions("1.0beta1", "1.0rc1") == -1
        # dev is earlier than alpha
        assert compare_versions("1.0dev1", "1.0alpha1") == -1

    def test_numeric_vs_string(self):
        """Numeric is greater than string (release > prerelease)"""
        # This tests edge cases in mixed type comparison
        assert compare_versions("1.0.0", "1.0.0rc1") == 1


class TestClassifyVersionChange:
    """Test the classify_version_change function"""

    def test_upgrade(self):
        """Upgrading version should be classified as UPGRADE"""
        result = classify_version_change("1.0", "2.0", "hash1", "hash2")
        assert result == VersionChangeType.UPGRADE

    def test_downgrade(self):
        """Downgrading version should be classified as DOWNGRADE"""
        result = classify_version_change("2.0", "1.0", "hash1", "hash2")
        assert result == VersionChangeType.DOWNGRADE

    def test_rebuild_same_version(self):
        """Same version but different hash should be REBUILD"""
        result = classify_version_change("1.0", "1.0", "hash1", "hash2")
        assert result == VersionChangeType.REBUILD

    def test_rebuild_same_hash(self):
        """Same hash should be REBUILD (edge case)"""
        result = classify_version_change("1.0", "2.0", "hash1", "hash1")
        assert result == VersionChangeType.REBUILD

    def test_unknown_left_none(self):
        """None left version should be UNKNOWN"""
        result = classify_version_change(None, "1.0", "hash1", "hash2")
        assert result == VersionChangeType.UNKNOWN

    def test_unknown_right_none(self):
        """None right version should be UNKNOWN"""
        result = classify_version_change("1.0", None, "hash1", "hash2")
        assert result == VersionChangeType.UNKNOWN

    def test_rebuild_both_none(self):
        """Both None versions should be REBUILD"""
        result = classify_version_change(None, None, "hash1", "hash2")
        assert result == VersionChangeType.REBUILD


class TestVersionDiff:
    """Test the VersionDiff model"""

    def test_version_change_summary_upgrade(self):
        """Upgrade summary should show version transition"""
        diff = VersionDiff(
            package_name="openssl",
            left_version="3.0.12",
            right_version="3.1.0",
            left_label="openssl-3.0.12",
            right_label="openssl-3.1.0",
            left_node_id=1,
            right_node_id=2,
            change_type=VersionChangeType.UPGRADE,
            package_type="lib",
        )
        assert diff.version_change_summary == "3.0.12 -> 3.1.0"

    def test_version_change_summary_downgrade(self):
        """Downgrade summary should show version transition"""
        diff = VersionDiff(
            package_name="openssl",
            left_version="3.1.0",
            right_version="3.0.12",
            left_label="openssl-3.1.0",
            right_label="openssl-3.0.12",
            left_node_id=1,
            right_node_id=2,
            change_type=VersionChangeType.DOWNGRADE,
            package_type="lib",
        )
        assert diff.version_change_summary == "3.1.0 -> 3.0.12"

    def test_version_change_summary_rebuild(self):
        """Rebuild summary should show version with (rebuilt)"""
        diff = VersionDiff(
            package_name="openssl",
            left_version="3.0.12",
            right_version="3.0.12",
            left_label="openssl-3.0.12",
            right_label="openssl-3.0.12",
            left_node_id=1,
            right_node_id=2,
            change_type=VersionChangeType.REBUILD,
            package_type="lib",
        )
        assert diff.version_change_summary == "3.0.12 (rebuilt)"

    def test_version_change_summary_unknown(self):
        """Unknown summary should show versions with (change)"""
        diff = VersionDiff(
            package_name="package",
            left_version=None,
            right_version="1.0",
            left_label="package",
            right_label="package-1.0",
            left_node_id=1,
            right_node_id=2,
            change_type=VersionChangeType.UNKNOWN,
            package_type="app",
        )
        assert diff.version_change_summary == "unknown -> 1.0 (change)"


class TestVersionComparisonResult:
    """Test the VersionComparisonResult model"""

    def _create_version_diff(
        self,
        name: str,
        left_ver: str,
        right_ver: str,
        change_type: VersionChangeType,
    ) -> VersionDiff:
        """Helper to create a VersionDiff"""
        return VersionDiff(
            package_name=name,
            left_version=left_ver,
            right_version=right_ver,
            left_label=f"{name}-{left_ver}",
            right_label=f"{name}-{right_ver}",
            left_node_id=1,
            right_node_id=2,
            change_type=change_type,
            package_type="lib",
        )

    def test_total_changes(self):
        """Total changes should sum all categories"""
        result = VersionComparisonResult(
            left_import_id=1,
            right_import_id=2,
            upgrades=[
                self._create_version_diff("pkg1", "1.0", "2.0", VersionChangeType.UPGRADE),
                self._create_version_diff("pkg2", "1.0", "1.1", VersionChangeType.UPGRADE),
            ],
            downgrades=[
                self._create_version_diff("pkg3", "2.0", "1.0", VersionChangeType.DOWNGRADE),
            ],
            rebuilds=[
                self._create_version_diff("pkg4", "1.0", "1.0", VersionChangeType.REBUILD),
            ],
            unknown_changes=[],
        )
        assert result.total_changes == 4
        assert result.upgrade_count == 2
        assert result.downgrade_count == 1
        assert result.rebuild_count == 1

    def test_empty_result(self):
        """Empty result should have zero counts"""
        result = VersionComparisonResult(
            left_import_id=1,
            right_import_id=2,
            upgrades=[],
            downgrades=[],
            rebuilds=[],
            unknown_changes=[],
        )
        assert result.total_changes == 0
        assert result.upgrade_count == 0
        assert result.downgrade_count == 0
        assert result.rebuild_count == 0


class TestDetectVersionChanges:
    """Test the detect_version_changes function"""

    def _mock_import_info(self, id: int, name: str) -> ImportInfo:
        """Create mock import info"""
        return ImportInfo(
            id=id,
            name=name,
            config_path="/etc/nixos",
            drv_path=f"/nix/store/{name}",
            imported_at=datetime.now(),
            node_count=100,
            edge_count=200,
        )

    def _mock_node(
        self,
        id: int,
        import_id: int,
        label: str,
        drv_hash: str,
        package_type: str = "lib",
    ) -> Node:
        """Create mock node"""
        return Node(
            id=id,
            import_id=import_id,
            drv_hash=drv_hash,
            drv_name=f"{label}.drv",
            label=label,
            package_type=package_type,
            depth=0,
            closure_size=100,
            metadata=None,
        )

    @patch('vizzy.services.comparison.compare_imports')
    def test_detect_upgrades(self, mock_compare):
        """Should detect version upgrades correctly"""
        # Setup mock comparison
        left_node = self._mock_node(1, 1, "openssl-3.0.12", "abc123")
        right_node = self._mock_node(2, 2, "openssl-3.1.0", "xyz789")

        mock_compare.return_value = ImportComparison(
            left_import=self._mock_import_info(1, "host1"),
            right_import=self._mock_import_info(2, "host2"),
            left_only_count=0,
            right_only_count=0,
            different_count=1,
            same_count=0,
            all_diffs=[
                NodeDiff(
                    label="openssl",
                    package_type="lib",
                    left_node=left_node,
                    right_node=right_node,
                    diff_type=DiffType.DIFFERENT_HASH,
                )
            ],
        )

        result = detect_version_changes(1, 2)

        assert len(result.upgrades) == 1
        assert result.upgrades[0].package_name == "openssl"
        assert result.upgrades[0].left_version == "3.0.12"
        assert result.upgrades[0].right_version == "3.1.0"
        assert result.upgrade_count == 1

    @patch('vizzy.services.comparison.compare_imports')
    def test_detect_downgrades(self, mock_compare):
        """Should detect version downgrades correctly"""
        left_node = self._mock_node(1, 1, "openssl-3.1.0", "xyz789")
        right_node = self._mock_node(2, 2, "openssl-3.0.12", "abc123")

        mock_compare.return_value = ImportComparison(
            left_import=self._mock_import_info(1, "host1"),
            right_import=self._mock_import_info(2, "host2"),
            left_only_count=0,
            right_only_count=0,
            different_count=1,
            same_count=0,
            all_diffs=[
                NodeDiff(
                    label="openssl",
                    package_type="lib",
                    left_node=left_node,
                    right_node=right_node,
                    diff_type=DiffType.DIFFERENT_HASH,
                )
            ],
        )

        result = detect_version_changes(1, 2)

        assert len(result.downgrades) == 1
        assert result.downgrades[0].package_name == "openssl"
        assert result.downgrade_count == 1

    @patch('vizzy.services.comparison.compare_imports')
    def test_detect_rebuilds(self, mock_compare):
        """Should detect rebuilds (same version, different hash)"""
        left_node = self._mock_node(1, 1, "openssl-3.0.12", "abc123")
        right_node = self._mock_node(2, 2, "openssl-3.0.12", "def456")

        mock_compare.return_value = ImportComparison(
            left_import=self._mock_import_info(1, "host1"),
            right_import=self._mock_import_info(2, "host2"),
            left_only_count=0,
            right_only_count=0,
            different_count=1,
            same_count=0,
            all_diffs=[
                NodeDiff(
                    label="openssl-3.0.12",
                    package_type="lib",
                    left_node=left_node,
                    right_node=right_node,
                    diff_type=DiffType.DIFFERENT_HASH,
                )
            ],
        )

        result = detect_version_changes(1, 2)

        assert len(result.rebuilds) == 1
        assert result.rebuilds[0].package_name == "openssl"
        assert result.rebuild_count == 1

    @patch('vizzy.services.comparison.compare_imports')
    def test_ignores_same_hash(self, mock_compare):
        """Should ignore nodes with SAME diff type"""
        left_node = self._mock_node(1, 1, "openssl-3.0.12", "abc123")
        right_node = self._mock_node(2, 2, "openssl-3.0.12", "abc123")

        mock_compare.return_value = ImportComparison(
            left_import=self._mock_import_info(1, "host1"),
            right_import=self._mock_import_info(2, "host2"),
            left_only_count=0,
            right_only_count=0,
            different_count=0,
            same_count=1,
            all_diffs=[
                NodeDiff(
                    label="openssl-3.0.12",
                    package_type="lib",
                    left_node=left_node,
                    right_node=right_node,
                    diff_type=DiffType.SAME,
                )
            ],
        )

        result = detect_version_changes(1, 2)

        assert result.total_changes == 0

    @patch('vizzy.services.comparison.compare_imports')
    def test_mixed_changes(self, mock_compare):
        """Should handle multiple types of changes"""
        mock_compare.return_value = ImportComparison(
            left_import=self._mock_import_info(1, "host1"),
            right_import=self._mock_import_info(2, "host2"),
            left_only_count=0,
            right_only_count=0,
            different_count=3,
            same_count=0,
            all_diffs=[
                # Upgrade
                NodeDiff(
                    label="openssl",
                    package_type="lib",
                    left_node=self._mock_node(1, 1, "openssl-3.0", "a"),
                    right_node=self._mock_node(2, 2, "openssl-3.1", "b"),
                    diff_type=DiffType.DIFFERENT_HASH,
                ),
                # Downgrade
                NodeDiff(
                    label="curl",
                    package_type="lib",
                    left_node=self._mock_node(3, 1, "curl-8.0", "c"),
                    right_node=self._mock_node(4, 2, "curl-7.9", "d"),
                    diff_type=DiffType.DIFFERENT_HASH,
                ),
                # Rebuild
                NodeDiff(
                    label="zlib-1.3",
                    package_type="lib",
                    left_node=self._mock_node(5, 1, "zlib-1.3", "e"),
                    right_node=self._mock_node(6, 2, "zlib-1.3", "f"),
                    diff_type=DiffType.DIFFERENT_HASH,
                ),
            ],
        )

        result = detect_version_changes(1, 2)

        assert result.upgrade_count == 1
        assert result.downgrade_count == 1
        assert result.rebuild_count == 1
        assert result.total_changes == 3


class TestGenerateVersionSummary:
    """Test the generate_version_summary function"""

    def _create_version_diff(
        self,
        name: str,
        change_type: VersionChangeType,
    ) -> VersionDiff:
        """Helper to create a VersionDiff"""
        return VersionDiff(
            package_name=name,
            left_version="1.0",
            right_version="2.0",
            left_label=f"{name}-1.0",
            right_label=f"{name}-2.0",
            left_node_id=1,
            right_node_id=2,
            change_type=change_type,
            package_type="lib",
        )

    def test_summary_with_upgrades(self):
        """Summary should include upgrade count"""
        result = VersionComparisonResult(
            left_import_id=1,
            right_import_id=2,
            upgrades=[
                self._create_version_diff("pkg1", VersionChangeType.UPGRADE),
                self._create_version_diff("pkg2", VersionChangeType.UPGRADE),
            ],
            downgrades=[],
            rebuilds=[],
            unknown_changes=[],
        )
        summary = generate_version_summary(result)
        assert "2 upgrades" in summary
        assert "Found 2 version changes" in summary

    def test_summary_with_single_upgrade(self):
        """Summary should use singular for single item"""
        result = VersionComparisonResult(
            left_import_id=1,
            right_import_id=2,
            upgrades=[self._create_version_diff("pkg1", VersionChangeType.UPGRADE)],
            downgrades=[],
            rebuilds=[],
            unknown_changes=[],
        )
        summary = generate_version_summary(result)
        assert "1 upgrade" in summary
        assert "upgrades" not in summary

    def test_summary_with_mixed(self):
        """Summary should include all categories"""
        result = VersionComparisonResult(
            left_import_id=1,
            right_import_id=2,
            upgrades=[self._create_version_diff("pkg1", VersionChangeType.UPGRADE)],
            downgrades=[self._create_version_diff("pkg2", VersionChangeType.DOWNGRADE)],
            rebuilds=[self._create_version_diff("pkg3", VersionChangeType.REBUILD)],
            unknown_changes=[self._create_version_diff("pkg4", VersionChangeType.UNKNOWN)],
        )
        summary = generate_version_summary(result)
        assert "1 upgrade" in summary
        assert "1 downgrade" in summary
        assert "1 rebuild" in summary
        assert "1 other change" in summary
        assert "Found 4 version changes" in summary

    def test_summary_empty(self):
        """Empty result should show no changes message"""
        result = VersionComparisonResult(
            left_import_id=1,
            right_import_id=2,
            upgrades=[],
            downgrades=[],
            rebuilds=[],
            unknown_changes=[],
        )
        summary = generate_version_summary(result)
        assert summary == "No version changes detected."
