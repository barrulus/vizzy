// Semantic Zoom Extension for Graph Navigation
// Adds level-of-detail rendering based on zoom level
// Task 8G-002: Added node aggregation support

/**
 * SemanticZoomNavigator extends GraphNavigator to add semantic zoom functionality.
 * When zoomed out, shows aggregated cluster view. When zoomed in, shows detailed nodes.
 * Task 8G-002: Now supports node aggregation at different detail levels.
 */
class SemanticZoomNavigator {
    constructor(container, options = {}) {
        this.container = container;
        this.svg = container.querySelector('svg');
        if (!this.svg) return;

        // Semantic zoom configuration
        this.importId = options.importId || container.dataset.importId;
        this.packageType = options.packageType || container.dataset.packageType || null;
        this.centerNodeId = options.centerNodeId || container.dataset.centerNodeId || null;
        this.semanticZoomEnabled = options.semanticZoom !== false && container.dataset.semanticZoom !== 'false';

        // Zoom level thresholds
        this.thresholds = {
            clusterToOverview: options.clusterToOverview || 0.3,
            overviewToDetailed: options.overviewToDetailed || 0.7,
        };

        // Current state
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.isPanning = false;
        this.lastPanX = 0;
        this.lastPanY = 0;
        this.currentZoomLevel = 2; // Start at detailed
        this.isLoading = false;

        // Task 8G-002: Aggregation state
        this.aggregationMode = options.aggregationMode || container.dataset.aggregationMode || 'none';
        this.aggregationThreshold = parseInt(options.aggregationThreshold || container.dataset.aggregationThreshold || 5);
        this.currentAggregateCount = 0;
        this.expandedAggregate = null; // Currently expanded aggregate ID

        // Debounce timer for semantic zoom updates
        this.semanticUpdateTimer = null;
        this.semanticUpdateDelay = 300; // ms

        // Touch support state
        this.lastTouchDistance = 0;
        this.lastTouchCenter = { x: 0, y: 0 };

        // Animation frame throttling for smooth performance
        this.pendingUpdate = false;

        this.init();
    }

    init() {
        // Wrap SVG content in a group for transformations
        if (!this.svg.querySelector('.pan-zoom-group')) {
            const content = this.svg.innerHTML;
            this.svg.innerHTML = `<g class="pan-zoom-group">${content}</g>`;
        }
        this.group = this.svg.querySelector('.pan-zoom-group');

        // Make SVG fill container
        this.svg.style.width = '100%';
        this.svg.style.height = '100%';
        this.svg.style.overflow = 'visible';
        this.container.style.overflow = 'hidden';

        // Set up event listeners
        this.container.addEventListener('wheel', this.handleZoom.bind(this), { passive: false });
        this.container.addEventListener('mousedown', this.startPan.bind(this));
        this.container.addEventListener('mousemove', this.doPan.bind(this));
        this.container.addEventListener('mouseup', this.endPan.bind(this));
        this.container.addEventListener('mouseleave', this.endPan.bind(this));

        // Touch support
        this.container.addEventListener('touchstart', this.handleTouchStart.bind(this), { passive: false });
        this.container.addEventListener('touchmove', this.handleTouchMove.bind(this), { passive: false });
        this.container.addEventListener('touchend', this.endPan.bind(this));

        // Add controls with semantic zoom indicator
        this.addControls();

        // Task 8G-002: Set up click handlers for aggregate nodes
        this.setupAggregateNodeHandlers();

        // Initial fit to container
        requestAnimationFrame(() => this.fitToContainer());
    }

    /**
     * Calculate the appropriate zoom level based on current scale
     */
    getZoomLevelForScale(scale) {
        if (scale < this.thresholds.clusterToOverview) {
            return 0; // Cluster
        } else if (scale < this.thresholds.overviewToDetailed) {
            return 1; // Overview
        } else {
            return 2; // Detailed
        }
    }

    /**
     * Get human-readable name for zoom level
     */
    getZoomLevelName(level) {
        const names = ['Clusters', 'Overview', 'Detailed'];
        return names[level] || 'Unknown';
    }

    handleZoom(e) {
        e.preventDefault();

        const rect = this.container.getBoundingClientRect();

        // Mouse position relative to container (in screen pixels)
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        // Convert to SVG viewBox coordinates (includes viewBox origin offset)
        const viewBox = this.svg.viewBox.baseVal;
        const vbX = viewBox.x || 0;
        const vbY = viewBox.y || 0;
        const svgX = viewBox.width > 0 ? mouseX * (viewBox.width / rect.width) + vbX : mouseX;
        const svgY = viewBox.height > 0 ? mouseY * (viewBox.height / rect.height) + vbY : mouseY;

        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(0.1, Math.min(5, this.scale * delta));

        // With transform="translate(tx,ty) scale(s)": output = s * P + translate
        // For point P under mouse at viewBox position M: M = s * P + translate
        // So P = (M - translate) / s
        // After zoom: M = newS * P + newTranslate
        // newTranslate = M - newS * (M - translate) / s
        // delta = newTranslate - translate = (M - translate) * (s - newS) / s
        this.translateX += (svgX - this.translateX) * (this.scale - newScale) / this.scale;
        this.translateY += (svgY - this.translateY) * (this.scale - newScale) / this.scale;
        this.scale = newScale;

        this.scheduleRender();
    }

    /**
     * Schedule a debounced update to the semantic zoom level
     */
    scheduleSemanticUpdate() {
        if (this.semanticUpdateTimer) {
            clearTimeout(this.semanticUpdateTimer);
        }

        this.semanticUpdateTimer = setTimeout(() => {
            this.checkAndUpdateSemanticLevel();
        }, this.semanticUpdateDelay);
    }

    /**
     * Check if semantic zoom level needs to change and update if so
     */
    async checkAndUpdateSemanticLevel() {
        const newLevel = this.getZoomLevelForScale(this.scale);

        if (newLevel !== this.currentZoomLevel && !this.isLoading) {
            await this.loadSemanticLevel(newLevel);
        }

        // Update the level indicator
        this.updateLevelIndicator();
    }

    /**
     * Load a new semantic zoom level from the server
     * Task 8G-002: Now includes aggregation parameters
     */
    async loadSemanticLevel(level, expandAggregate = null) {
        if (!this.importId || this.isLoading) return;

        this.isLoading = true;
        this.showLoadingIndicator();

        try {
            const params = new URLSearchParams({
                zoom_level: level,
                scale: this.scale,
                aggregation_mode: this.aggregationMode,
                aggregation_threshold: this.aggregationThreshold,
            });

            if (this.packageType) {
                params.set('package_type', this.packageType);
            }
            if (this.centerNodeId) {
                params.set('center_node_id', this.centerNodeId);
            }
            // Task 8G-002: Support expanding an aggregate
            if (expandAggregate) {
                params.set('expand_aggregate', expandAggregate);
                this.expandedAggregate = expandAggregate;
            }

            const response = await fetch(`/api/semantic-zoom/${this.importId}?${params}`);
            if (!response.ok) {
                throw new Error(`Failed to load zoom level: ${response.status}`);
            }

            const data = await response.json();

            // Update the SVG content
            this.updateSvgContent(data.svg);
            this.currentZoomLevel = data.zoom_level;

            // Task 8G-002: Track aggregate count
            this.currentAggregateCount = data.aggregate_count || 0;

            // Dispatch custom event for other components to react
            this.container.dispatchEvent(new CustomEvent('semanticZoomChange', {
                detail: {
                    level: data.zoom_level,
                    levelName: this.getZoomLevelName(data.zoom_level),
                    scale: this.scale,
                    clusterCount: data.cluster_count,
                    nodeCount: data.node_count,
                    edgeCount: data.edge_count,
                    // Task 8G-002: Include aggregation info
                    aggregateCount: data.aggregate_count,
                    aggregationMode: data.aggregation_mode,
                },
                bubbles: true,
            }));

            // Update the aggregation indicator
            this.updateAggregationIndicator();

        } catch (error) {
            console.error('SemanticZoomNavigator: Failed to load level', error);
        } finally {
            this.isLoading = false;
            this.hideLoadingIndicator();
        }
    }

    /**
     * Task 8G-002: Expand an aggregate to show its contained nodes
     */
    async expandAggregate(aggregateId) {
        if (!aggregateId || this.isLoading) return;

        // Load with expand_aggregate parameter
        await this.loadSemanticLevel(this.currentZoomLevel, aggregateId);
    }

    /**
     * Task 8G-002: Collapse back from an expanded aggregate view
     */
    async collapseAggregate() {
        if (!this.expandedAggregate) return;

        this.expandedAggregate = null;
        await this.loadSemanticLevel(this.currentZoomLevel);
    }

    /**
     * Task 8G-002: Set the aggregation mode
     */
    setAggregationMode(mode) {
        if (['none', 'prefix', 'depth'].includes(mode)) {
            this.aggregationMode = mode;
            this.expandedAggregate = null;

            // Reload current level with new aggregation mode
            if (this.semanticZoomEnabled && this.importId) {
                this.loadSemanticLevel(this.currentZoomLevel);
            }

            // Update controls if they exist
            this.updateAggregationControls();
        }
    }

    /**
     * Task 8G-002: Set the aggregation threshold
     */
    setAggregationThreshold(threshold) {
        const t = parseInt(threshold);
        if (t >= 2 && t <= 50) {
            this.aggregationThreshold = t;
            this.expandedAggregate = null;

            // Reload current level with new threshold
            if (this.semanticZoomEnabled && this.importId) {
                this.loadSemanticLevel(this.currentZoomLevel);
            }
        }
    }

    /**
     * Task 8G-002: Update the aggregation mode selector in controls
     */
    updateAggregationControls() {
        const selector = this.container.querySelector('.aggregation-mode-selector');
        if (selector) {
            selector.querySelectorAll('.aggregation-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.mode === this.aggregationMode);
            });
        }
    }

    /**
     * Task 8G-002: Update the aggregation indicator
     */
    updateAggregationIndicator() {
        const indicator = this.container.querySelector('.aggregation-indicator');
        if (indicator) {
            if (this.currentAggregateCount > 0) {
                indicator.textContent = `${this.currentAggregateCount} aggregates`;
                indicator.classList.add('visible');
            } else {
                indicator.classList.remove('visible');
            }
        }
    }

    /**
     * Update the SVG content while preserving transform state
     */
    updateSvgContent(newSvg) {
        // Parse the new SVG
        const parser = new DOMParser();
        const doc = parser.parseFromString(newSvg, 'image/svg+xml');
        const newSvgElement = doc.querySelector('svg');

        if (!newSvgElement) {
            console.error('SemanticZoomNavigator: Invalid SVG content');
            return;
        }

        // Get the content (everything inside the svg)
        const newContent = newSvgElement.innerHTML;

        // Preserve viewBox if present
        const viewBox = newSvgElement.getAttribute('viewBox');
        if (viewBox) {
            this.svg.setAttribute('viewBox', viewBox);
        }

        // Update the pan-zoom group content
        this.group.innerHTML = newContent;

        // Re-fit the new content to the container
        requestAnimationFrame(() => this.fitToContainer());
    }

    /**
     * Show loading indicator during level transitions
     */
    showLoadingIndicator() {
        let indicator = this.container.querySelector('.semantic-zoom-loading');
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.className = 'semantic-zoom-loading';
            indicator.innerHTML = '<div class="spinner"></div><span>Loading...</span>';
            this.container.appendChild(indicator);
        }
        indicator.classList.add('visible');
    }

    /**
     * Hide loading indicator
     */
    hideLoadingIndicator() {
        const indicator = this.container.querySelector('.semantic-zoom-loading');
        if (indicator) {
            indicator.classList.remove('visible');
        }
    }

    /**
     * Update the zoom level indicator in controls
     */
    updateLevelIndicator() {
        const indicator = this.container.querySelector('.zoom-level-indicator');
        if (indicator) {
            const levelName = this.getZoomLevelName(this.currentZoomLevel);
            indicator.textContent = levelName;
            indicator.dataset.level = this.currentZoomLevel;
        }
    }

    startPan(e) {
        if (e.target.closest('a')) return;

        e.preventDefault(); // Prevent text selection
        this.isPanning = true;
        this.lastPanX = e.clientX;
        this.lastPanY = e.clientY;
        this.container.style.cursor = 'grabbing';
    }

    doPan(e) {
        if (!this.isPanning) return;

        // Convert screen pixel delta to viewBox coordinates
        // Use uniform scale for consistent panning in all directions
        const rect = this.container.getBoundingClientRect();
        const viewBox = this.svg.viewBox.baseVal;
        const scale = viewBox.width > 0 && viewBox.height > 0
            ? Math.max(viewBox.width / rect.width, viewBox.height / rect.height)
            : 1;

        const dx = (e.clientX - this.lastPanX) * scale;
        const dy = (e.clientY - this.lastPanY) * scale;

        this.translateX += dx;
        this.translateY += dy;
        this.lastPanX = e.clientX;
        this.lastPanY = e.clientY;

        this.scheduleRender();
    }

    scheduleRender() {
        if (this.pendingUpdate) return;
        this.pendingUpdate = true;
        requestAnimationFrame(() => {
            this.applyTransform();
            this.pendingUpdate = false;
        });
    }

    endPan() {
        this.isPanning = false;
        this.container.style.cursor = 'grab';
    }

    handleTouchStart(e) {
        if (e.touches.length === 1) {
            const touch = e.touches[0];
            this.isPanning = true;
            this.lastPanX = touch.clientX;
            this.lastPanY = touch.clientY;
        } else if (e.touches.length === 2) {
            e.preventDefault();
            this.isPanning = false;
            this.lastTouchDistance = this.getTouchDistance(e.touches);
            this.lastTouchCenter = this.getTouchCenter(e.touches);
        }
    }

    handleTouchMove(e) {
        if (e.touches.length === 1 && this.isPanning) {
            const touch = e.touches[0];
            // Convert screen pixel delta to viewBox coordinates
            // Use uniform scale for consistent panning in all directions
            const rect = this.container.getBoundingClientRect();
            const viewBox = this.svg.viewBox.baseVal;
            const scale = viewBox.width > 0 && viewBox.height > 0
                ? Math.max(viewBox.width / rect.width, viewBox.height / rect.height)
                : 1;

            const dx = (touch.clientX - this.lastPanX) * scale;
            const dy = (touch.clientY - this.lastPanY) * scale;

            this.translateX += dx;
            this.translateY += dy;
            this.lastPanX = touch.clientX;
            this.lastPanY = touch.clientY;

            this.scheduleRender();
        } else if (e.touches.length === 2) {
            e.preventDefault();
            const distance = this.getTouchDistance(e.touches);
            const center = this.getTouchCenter(e.touches);
            const rect = this.container.getBoundingClientRect();

            // Convert pinch center to SVG viewBox coordinates
            const mouseX = center.x - rect.left;
            const mouseY = center.y - rect.top;
            const viewBox = this.svg.viewBox.baseVal;
            const vbX = viewBox.x || 0;
            const vbY = viewBox.y || 0;
            const svgX = viewBox.width > 0 ? mouseX * (viewBox.width / rect.width) + vbX : mouseX;
            const svgY = viewBox.height > 0 ? mouseY * (viewBox.height / rect.height) + vbY : mouseY;

            const scaleChange = distance / this.lastTouchDistance;
            const newScale = Math.max(0.1, Math.min(5, this.scale * scaleChange));

            // Same formula as handleZoom: delta = (M - translate) * (s - newS) / s
            this.translateX += (svgX - this.translateX) * (this.scale - newScale) / this.scale;
            this.translateY += (svgY - this.translateY) * (this.scale - newScale) / this.scale;
            this.scale = newScale;

            this.lastTouchDistance = distance;
            this.lastTouchCenter = center;

            this.scheduleRender();
        }
    }

    getTouchDistance(touches) {
        const dx = touches[0].clientX - touches[1].clientX;
        const dy = touches[0].clientY - touches[1].clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    getTouchCenter(touches) {
        return {
            x: (touches[0].clientX + touches[1].clientX) / 2,
            y: (touches[0].clientY + touches[1].clientY) / 2
        };
    }

    applyTransform() {
        // Order: translate first (in screen coords), then scale
        this.group.setAttribute('transform',
            `translate(${this.translateX}, ${this.translateY}) scale(${this.scale})`
        );
    }

    reset() {
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.applyTransform();
        this.fitToContainer();
        // Note: Reset no longer auto-switches semantic level - use C/O/D buttons
    }

    fitToContainer(retryCount = 0) {
        const containerRect = this.container.getBoundingClientRect();

        // Retry if container not ready
        if ((containerRect.width === 0 || containerRect.height === 0) && retryCount < 10) {
            setTimeout(() => this.fitToContainer(retryCount + 1), 50);
            return;
        }

        // Get actual rendered bounds using getBBox on the group
        let bbox;
        try {
            bbox = this.group.getBBox();
        } catch (err) {
            if (retryCount < 10) {
                setTimeout(() => this.fitToContainer(retryCount + 1), 50);
            }
            return;
        }

        if (bbox.width === 0 || bbox.height === 0) {
            if (retryCount < 10) {
                setTimeout(() => this.fitToContainer(retryCount + 1), 50);
            }
            return;
        }

        // Get viewBox to work in SVG coordinates
        const viewBox = this.svg.viewBox.baseVal;
        const vbWidth = viewBox.width > 0 ? viewBox.width : containerRect.width;
        const vbHeight = viewBox.height > 0 ? viewBox.height : containerRect.height;
        const vbX = viewBox.x || 0;
        const vbY = viewBox.y || 0;

        // Calculate scale to fit bbox within viewBox (with padding in SVG units)
        const paddingRatio = 0.05; // 5% padding
        const availableWidth = vbWidth * (1 - paddingRatio * 2);
        const availableHeight = vbHeight * (1 - paddingRatio * 2);

        const scaleX = availableWidth / bbox.width;
        const scaleY = availableHeight / bbox.height;
        this.scale = Math.min(scaleX, scaleY, 1.5);

        // Center of viewBox (in SVG coordinates)
        const viewBoxCenterX = vbX + vbWidth / 2;
        const viewBoxCenterY = vbY + vbHeight / 2;

        // Center of content bbox
        const bboxCenterX = bbox.x + bbox.width / 2;
        const bboxCenterY = bbox.y + bbox.height / 2;

        // With transform="translate(tx,ty) scale(s)": screenPos = s * content + translate
        // We want: s * bboxCenter + translate = viewBoxCenter
        // translate = viewBoxCenter - s * bboxCenter
        this.translateX = viewBoxCenterX - this.scale * bboxCenterX;
        this.translateY = viewBoxCenterY - this.scale * bboxCenterY;

        this.applyTransform();
    }

    /**
     * Manually set the semantic zoom level
     */
    setZoomLevel(level) {
        if (level >= 0 && level <= 2 && level !== this.currentZoomLevel) {
            this.loadSemanticLevel(level);
        }
    }

    addControls() {
        const existing = this.container.querySelector('.graph-controls');
        if (existing) existing.remove();

        const controls = document.createElement('div');
        controls.className = 'graph-controls semantic-zoom-controls';

        // Build control HTML based on whether semantic zoom is enabled
        let controlsHtml = `
            <button class="zoom-in" title="Zoom In (scroll up)">+</button>
            <button class="zoom-out" title="Zoom Out (scroll down)">-</button>
            <button class="zoom-reset" title="Reset View">&#x21BA;</button>
        `;

        if (this.semanticZoomEnabled && this.importId) {
            controlsHtml += `
                <div class="zoom-level-divider"></div>
                <div class="zoom-level-selector" title="Semantic zoom level">
                    <button class="zoom-level-btn" data-level="0" title="Cluster view">C</button>
                    <button class="zoom-level-btn" data-level="1" title="Overview">O</button>
                    <button class="zoom-level-btn active" data-level="2" title="Detailed">D</button>
                </div>
                <span class="zoom-level-indicator" data-level="2">Detailed</span>
                <div class="zoom-level-divider"></div>
                <!-- Task 8G-002: Aggregation controls -->
                <div class="aggregation-mode-selector" title="Node aggregation mode">
                    <button class="aggregation-btn ${this.aggregationMode === 'none' ? 'active' : ''}"
                            data-mode="none" title="No aggregation">N</button>
                    <button class="aggregation-btn ${this.aggregationMode === 'prefix' ? 'active' : ''}"
                            data-mode="prefix" title="Aggregate by label prefix (e.g., python3.11-*)">P</button>
                    <button class="aggregation-btn ${this.aggregationMode === 'depth' ? 'active' : ''}"
                            data-mode="depth" title="Aggregate by dependency depth">D</button>
                </div>
                <span class="aggregation-indicator" title="Number of aggregated groups"></span>
            `;
        }

        controls.innerHTML = controlsHtml;

        // Standard zoom controls (no automatic semantic zoom - use C/O/D buttons)
        controls.querySelector('.zoom-in').addEventListener('click', () => {
            this.scale = Math.min(5, this.scale * 1.2);
            this.applyTransform();
        });

        controls.querySelector('.zoom-out').addEventListener('click', () => {
            this.scale = Math.max(0.1, this.scale / 1.2);
            this.applyTransform();
        });

        controls.querySelector('.zoom-reset').addEventListener('click', () => {
            this.reset();
        });

        // Semantic zoom level buttons
        if (this.semanticZoomEnabled && this.importId) {
            controls.querySelectorAll('.zoom-level-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const level = parseInt(btn.dataset.level);
                    this.setZoomLevel(level);

                    // Update button states
                    controls.querySelectorAll('.zoom-level-btn').forEach(b => {
                        b.classList.toggle('active', parseInt(b.dataset.level) === level);
                    });
                });
            });

            // Task 8G-002: Aggregation mode buttons
            controls.querySelectorAll('.aggregation-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const mode = btn.dataset.mode;
                    this.setAggregationMode(mode);

                    // Update button states
                    controls.querySelectorAll('.aggregation-btn').forEach(b => {
                        b.classList.toggle('active', b.dataset.mode === mode);
                    });
                });
            });
        }

        this.container.style.position = 'relative';
        this.container.appendChild(controls);
    }

    /**
     * Task 8G-002: Handle clicks on aggregate nodes in the SVG
     * Aggregate nodes have hrefs like /api/semantic-zoom/{id}?expand_aggregate={agg_id}
     */
    setupAggregateNodeHandlers() {
        this.svg.addEventListener('click', (e) => {
            const link = e.target.closest('a');
            if (!link) return;

            const href = link.getAttribute('xlink:href') || link.getAttribute('href');
            if (href && href.includes('expand_aggregate=')) {
                e.preventDefault();

                // Extract aggregate ID from URL
                const url = new URL(href, window.location.origin);
                const aggregateId = url.searchParams.get('expand_aggregate');

                if (aggregateId) {
                    this.expandAggregate(aggregateId);
                }
            }
        });
    }
}

// Factory function to create appropriate navigator
function createGraphNavigator(container, options = {}) {
    const semanticEnabled = options.semanticZoom !== false &&
                           container.dataset.semanticZoom !== 'false' &&
                           container.dataset.importId;

    if (semanticEnabled) {
        return new SemanticZoomNavigator(container, options);
    } else {
        // Fall back to regular GraphNavigator if available
        if (typeof GraphNavigator !== 'undefined') {
            return new GraphNavigator(container);
        }
        // Otherwise use SemanticZoomNavigator with semantic disabled
        return new SemanticZoomNavigator(container, { ...options, semanticZoom: false });
    }
}

// Initialize semantic zoom navigators
function initSemanticZoomNavigators() {
    document.querySelectorAll('.graph-container[data-semantic-zoom="true"]').forEach(container => {
        if (container._semanticZoomNavigator) return;
        container._semanticZoomNavigator = new SemanticZoomNavigator(container);
    });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', initSemanticZoomNavigators);

// Re-initialize after HTMX swaps
document.body.addEventListener('htmx:afterSwap', (e) => {
    requestAnimationFrame(() => {
        const containers = e.detail.target.querySelectorAll('.graph-container[data-semantic-zoom="true"]');
        containers.forEach(container => {
            container._semanticZoomNavigator = new SemanticZoomNavigator(container);
        });
    });
});

document.body.addEventListener('htmx:oobAfterSwap', (e) => {
    requestAnimationFrame(() => {
        const containers = e.detail.target.querySelectorAll('.graph-container[data-semantic-zoom="true"]');
        containers.forEach(container => {
            container._semanticZoomNavigator = new SemanticZoomNavigator(container);
        });
    });
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SemanticZoomNavigator, createGraphNavigator };
}
