"""Tests for Why Chain API endpoint (Phase 8E-005)

These tests validate the API endpoints for the Why Chain feature,
which exposes the "Why is package X in my closure?" functionality
to the frontend.

Endpoint coverage:
- GET /analyze/why/{import_id}/{node_id} - Full HTML page
- GET /analyze/why/{import_id}/{node_id}/partial - HTMX partial
- GET /analyze/api/why/{import_id}/{node_id} - JSON API
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from fastapi.testclient import TestClient

from vizzy.models import (
    Node,
    ImportInfo,
    WhyChainQuery,
    WhyChainResult,
    AttributionGroup,
    EssentialityStatus,
    DependencyDirection,
)


# =============================================================================
# Helper Functions
# =============================================================================


def make_node(
    id: int,
    label: str,
    import_id: int = 1,
    package_type: str = "app",
    is_top_level: bool = False,
    top_level_source: str | None = None,
    closure_size: int = 10,
) -> Node:
    """Helper to create a Node for testing."""
    return Node(
        id=id,
        import_id=import_id,
        drv_hash=f"hash{id}",
        drv_name=f"{label}.drv",
        label=label,
        package_type=package_type,
        depth=1,
        closure_size=closure_size,
        metadata=None,
        is_top_level=is_top_level,
        top_level_source=top_level_source,
    )


def make_import_info(id: int = 1, name: str = "test-host") -> ImportInfo:
    """Helper to create an ImportInfo for testing."""
    return ImportInfo(
        id=id,
        name=name,
        config_path="/etc/nixos",
        drv_path="/nix/store/test.drv",
        imported_at=datetime.now(),
        node_count=1000,
        edge_count=5000,
    )


def make_why_chain_result(
    target: Node,
    import_id: int = 1,
    groups: list[AttributionGroup] | None = None,
    direct_dependents: list[Node] | None = None,
    total_top_level: int = 5,
    total_paths: int = 10,
    essentiality: EssentialityStatus = EssentialityStatus.ESSENTIAL,
    computation_time_ms: float = 50.0,
) -> WhyChainResult:
    """Helper to create a WhyChainResult for testing."""
    query = WhyChainQuery(
        target_node_id=target.id,
        import_id=import_id,
        direction=DependencyDirection.REVERSE,
        max_depth=10,
        max_paths=100,
        include_build_deps=True,
    )

    return WhyChainResult(
        target=target,
        query=query,
        direct_dependents=direct_dependents or [],
        attribution_groups=groups or [],
        total_top_level_dependents=total_top_level,
        total_paths_found=total_paths,
        essentiality=essentiality,
        computation_time_ms=computation_time_ms,
        cached_at=None,
    )


def make_attribution_group(
    via_node: Node,
    top_level_packages: list[Node],
    target: Node,
) -> AttributionGroup:
    """Helper to create an AttributionGroup for testing."""
    shortest_path = [top_level_packages[0], via_node, target] if top_level_packages else [via_node, target]
    return AttributionGroup(
        via_node=via_node,
        top_level_packages=top_level_packages,
        shortest_path=shortest_path,
        total_dependents=len(top_level_packages),
        common_path_suffix=[via_node, target],
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_graph_service():
    """Mock the graph service for import lookups."""
    with patch("vizzy.routes.analyze.graph_service") as mock:
        yield mock


@pytest.fixture
def mock_why_chain_service():
    """Mock the why_chain service for result computation."""
    with patch("vizzy.routes.analyze.why_chain_service") as mock:
        yield mock


@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app."""
    from vizzy.main import app
    return TestClient(app)


# =============================================================================
# HTML Page Endpoint Tests
# =============================================================================


class TestWhyChainView:
    """Test the full HTML page endpoint: GET /analyze/why/{import_id}/{node_id}"""

    def test_import_not_found(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return 404 when import not found."""
        mock_graph_service.get_import.return_value = None

        response = test_client.get("/analyze/why/999/123")

        assert response.status_code == 404
        assert "Import not found" in response.text

    def test_node_not_found(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return 404 when target node not found."""
        mock_graph_service.get_import.return_value = make_import_info()
        mock_why_chain_service.build_why_chain_result.return_value = None

        response = test_client.get("/analyze/why/1/999")

        assert response.status_code == 404
        assert "Node not found" in response.text

    def test_successful_response(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return HTML with why chain result."""
        import_info = make_import_info()
        target = make_node(5, "glibc", package_type="lib")
        firefox = make_node(1, "firefox", is_top_level=True)
        openssl = make_node(3, "openssl")

        group = make_attribution_group(openssl, [firefox], target)
        result = make_why_chain_result(target, groups=[group], direct_dependents=[openssl])

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = (
            "glibc is needed by 5 top-level packages"
        )

        response = test_client.get("/analyze/why/1/5")

        assert response.status_code == 200
        assert "glibc" in response.text
        assert "Why is" in response.text

    def test_query_parameters(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should pass query parameters to service."""
        import_info = make_import_info()
        target = make_node(5, "glibc")
        result = make_why_chain_result(target)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get(
            "/analyze/why/1/5?max_depth=20&max_groups=15&include_build_deps=false"
        )

        assert response.status_code == 200

        # Verify the service was called with correct parameters
        call_args = mock_why_chain_service.build_why_chain_result.call_args
        assert call_args.kwargs["max_groups"] == 15
        query = call_args.kwargs["query"]
        assert query.max_depth == 20
        assert query.include_build_deps is False

    def test_essentiality_badge_essential(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should show Essential badge for essential packages."""
        import_info = make_import_info()
        target = make_node(5, "glibc")
        result = make_why_chain_result(target, essentiality=EssentialityStatus.ESSENTIAL)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get("/analyze/why/1/5")

        assert response.status_code == 200
        assert "Essential" in response.text

    def test_essentiality_badge_orphan(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should show Orphan badge for orphan packages."""
        import_info = make_import_info()
        target = make_node(5, "orphan-pkg")
        result = make_why_chain_result(
            target,
            groups=[],
            total_top_level=0,
            total_paths=0,
            essentiality=EssentialityStatus.ORPHAN,
        )

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = (
            "orphan-pkg is not required by any top-level package"
        )

        response = test_client.get("/analyze/why/1/5")

        assert response.status_code == 200
        assert "Orphan" in response.text


# =============================================================================
# HTMX Partial Endpoint Tests
# =============================================================================


class TestWhyChainPartial:
    """Test the HTMX partial endpoint: GET /analyze/why/{import_id}/{node_id}/partial"""

    def test_import_not_found(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return error HTML when import not found."""
        mock_graph_service.get_import.return_value = None

        response = test_client.get("/analyze/why/999/123/partial")

        assert response.status_code == 404
        assert "Import not found" in response.text
        assert "text-red-500" in response.text

    def test_node_not_found(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return error HTML when node not found."""
        mock_graph_service.get_import.return_value = make_import_info()
        mock_why_chain_service.build_why_chain_result.return_value = None

        response = test_client.get("/analyze/why/1/999/partial")

        assert response.status_code == 404
        assert "Node not found" in response.text

    def test_successful_partial(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return HTML partial for HTMX."""
        import_info = make_import_info()
        target = make_node(5, "glibc")
        result = make_why_chain_result(target)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = "summary text"

        response = test_client.get("/analyze/why/1/5/partial")

        assert response.status_code == 200
        assert "why-chain-result" in response.text
        assert "glibc" in response.text

    def test_partial_is_smaller_than_full(self, mock_graph_service, mock_why_chain_service, test_client):
        """Partial should be smaller than full page (no base template)."""
        import_info = make_import_info()
        target = make_node(5, "glibc")
        result = make_why_chain_result(target)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = "summary"

        full_response = test_client.get("/analyze/why/1/5")
        partial_response = test_client.get("/analyze/why/1/5/partial")

        # Partial should not include base template elements
        assert "<!DOCTYPE html>" in full_response.text
        assert "<!DOCTYPE html>" not in partial_response.text

        # Partial should be smaller
        assert len(partial_response.text) < len(full_response.text)


# =============================================================================
# JSON API Endpoint Tests
# =============================================================================


class TestWhyChainApi:
    """Test the JSON API endpoint: GET /analyze/api/why/{import_id}/{node_id}"""

    def test_import_not_found(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return JSON error when import not found."""
        mock_graph_service.get_import.return_value = None

        response = test_client.get("/analyze/api/why/999/123")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "Import not found"
        assert data["import_id"] == 999

    def test_node_not_found(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return JSON error when node not found."""
        mock_graph_service.get_import.return_value = make_import_info()
        mock_why_chain_service.build_why_chain_result.return_value = None

        response = test_client.get("/analyze/api/why/1/999")

        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "Node not found"
        assert data["node_id"] == 999

    def test_successful_json_response(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return complete JSON response."""
        import_info = make_import_info()
        target = make_node(5, "glibc", package_type="lib", closure_size=500)
        firefox = make_node(1, "firefox", is_top_level=True)
        openssl = make_node(3, "openssl")

        group = make_attribution_group(openssl, [firefox], target)
        result = make_why_chain_result(
            target,
            groups=[group],
            direct_dependents=[openssl],
            total_top_level=5,
            total_paths=10,
            essentiality=EssentialityStatus.ESSENTIAL,
            computation_time_ms=45.5,
        )

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = (
            "glibc is needed by 5 top-level packages"
        )

        response = test_client.get("/analyze/api/why/1/5")

        assert response.status_code == 200
        data = response.json()

        # Check target
        assert data["target"]["id"] == 5
        assert data["target"]["label"] == "glibc"
        assert data["target"]["package_type"] == "lib"
        assert data["target"]["closure_size"] == 500

        # Check summary
        assert "glibc is needed by 5 top-level packages" in data["summary"]

        # Check metrics
        assert data["total_top_level_dependents"] == 5
        assert data["total_paths_found"] == 10
        assert data["essentiality"] == "essential"
        assert data["computation_time_ms"] == 45.5
        assert data["cached"] is False

        # Check attribution groups
        assert len(data["attribution_groups"]) == 1
        assert data["attribution_groups"][0]["via_label"] == "openssl"
        assert data["attribution_groups"][0]["total_dependents"] == 1

        # Check direct dependents
        assert len(data["direct_dependents"]) == 1
        assert data["direct_dependents"][0]["label"] == "openssl"

    def test_json_response_limits_arrays(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should limit array sizes in JSON response."""
        import_info = make_import_info()
        target = make_node(5, "glibc")

        # Create many direct dependents
        direct_deps = [make_node(i, f"dep{i}") for i in range(30)]

        # Create a group with many top-level packages
        via = make_node(100, "via")
        top_levels = [make_node(i + 200, f"pkg{i}", is_top_level=True) for i in range(20)]
        group = make_attribution_group(via, top_levels, target)

        result = make_why_chain_result(
            target,
            groups=[group],
            direct_dependents=direct_deps,
        )

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get("/analyze/api/why/1/5")

        assert response.status_code == 200
        data = response.json()

        # Direct dependents should be limited to 20
        assert len(data["direct_dependents"]) == 20

        # Top-level packages in groups should be limited to 10
        assert len(data["attribution_groups"][0]["top_level_packages"]) == 10

    def test_json_response_cached_flag(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should indicate when result is from cache."""
        import_info = make_import_info()
        target = make_node(5, "glibc")
        result = make_why_chain_result(target)
        result.cached_at = datetime.now()

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get("/analyze/api/why/1/5")

        assert response.status_code == 200
        data = response.json()
        assert data["cached"] is True

    def test_json_query_parameters(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should accept and use query parameters."""
        import_info = make_import_info()
        target = make_node(5, "glibc")
        result = make_why_chain_result(target)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get(
            "/analyze/api/why/1/5?max_depth=25&max_groups=20&include_build_deps=false"
        )

        assert response.status_code == 200

        # Verify service was called with correct parameters
        call_args = mock_why_chain_service.build_why_chain_result.call_args
        assert call_args.kwargs["max_groups"] == 20
        query = call_args.kwargs["query"]
        assert query.max_depth == 25
        assert query.include_build_deps is False

    def test_json_essentiality_values(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should return correct essentiality string values."""
        import_info = make_import_info()
        target = make_node(5, "test")

        for status, expected_value in [
            (EssentialityStatus.ESSENTIAL, "essential"),
            (EssentialityStatus.REMOVABLE, "removable"),
            (EssentialityStatus.BUILD_ONLY, "build_only"),
            (EssentialityStatus.ORPHAN, "orphan"),
        ]:
            result = make_why_chain_result(target, essentiality=status)

            mock_graph_service.get_import.return_value = import_info
            mock_why_chain_service.build_why_chain_result.return_value = result
            mock_why_chain_service.summarize_attribution.return_value = ""

            response = test_client.get("/analyze/api/why/1/5")

            assert response.status_code == 200
            data = response.json()
            assert data["essentiality"] == expected_value


# =============================================================================
# Query Parameter Validation Tests
# =============================================================================


class TestQueryParameterValidation:
    """Test query parameter validation."""

    def test_max_depth_minimum(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should reject max_depth < 1."""
        mock_graph_service.get_import.return_value = make_import_info()

        response = test_client.get("/analyze/why/1/5?max_depth=0")

        assert response.status_code == 422  # Validation error

    def test_max_depth_maximum(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should reject max_depth > 50."""
        mock_graph_service.get_import.return_value = make_import_info()

        response = test_client.get("/analyze/why/1/5?max_depth=100")

        assert response.status_code == 422  # Validation error

    def test_max_groups_minimum(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should reject max_groups < 1."""
        mock_graph_service.get_import.return_value = make_import_info()

        response = test_client.get("/analyze/why/1/5?max_groups=0")

        assert response.status_code == 422  # Validation error

    def test_max_groups_maximum(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should reject max_groups > 50."""
        mock_graph_service.get_import.return_value = make_import_info()

        response = test_client.get("/analyze/why/1/5?max_groups=100")

        assert response.status_code == 422  # Validation error

    def test_default_parameters(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should use sensible defaults when no parameters provided."""
        import_info = make_import_info()
        target = make_node(5, "glibc")
        result = make_why_chain_result(target)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get("/analyze/api/why/1/5")

        assert response.status_code == 200

        # Check defaults were used
        call_args = mock_why_chain_service.build_why_chain_result.call_args
        assert call_args.kwargs["max_groups"] == 10
        query = call_args.kwargs["query"]
        assert query.max_depth == 10
        assert query.include_build_deps is True


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_attribution_groups(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should handle empty attribution groups gracefully."""
        import_info = make_import_info()
        target = make_node(5, "orphan")
        result = make_why_chain_result(
            target,
            groups=[],
            total_top_level=0,
            total_paths=0,
            essentiality=EssentialityStatus.ORPHAN,
        )

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = (
            "orphan is not required by any top-level package"
        )

        response = test_client.get("/analyze/api/why/1/5")

        assert response.status_code == 200
        data = response.json()
        assert data["attribution_groups"] == []
        assert data["total_top_level_dependents"] == 0

    def test_very_long_package_names(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should handle very long package names."""
        import_info = make_import_info()
        long_name = "a" * 200 + "-very-long-package-name-1.0.0"
        target = make_node(5, long_name)
        result = make_why_chain_result(target)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get("/analyze/api/why/1/5")

        assert response.status_code == 200
        data = response.json()
        assert data["target"]["label"] == long_name

    def test_special_characters_in_labels(self, mock_graph_service, mock_why_chain_service, test_client):
        """Should handle special characters in package labels."""
        import_info = make_import_info()
        target = make_node(5, "c++-17-library_2.0+beta")
        result = make_why_chain_result(target)

        mock_graph_service.get_import.return_value = import_info
        mock_why_chain_service.build_why_chain_result.return_value = result
        mock_why_chain_service.summarize_attribution.return_value = ""

        response = test_client.get("/analyze/api/why/1/5")

        assert response.status_code == 200
        data = response.json()
        assert data["target"]["label"] == "c++-17-library_2.0+beta"
